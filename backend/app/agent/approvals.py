"""Human-in-the-loop for sensitive tool calls.

Agent side (`handle_call` -> `request_approval`): a tool marked `requires_approval` is NOT executed.
The call is validated and stored as a pending Approval, and the model is told it is pending.

Human side (`decide`): a support agent approves or rejects. Approving runs the tool through the tool
ledger with the ORIGINAL tool_call_id, so the action happens exactly once however many times the
decision arrives. Both outcomes append a plain-language follow-up to the conversation, so the employee
(and the model on the next turn) see what happened.

Guards, each tested:
- only a support agent of the same tenant can decide (RLS hides other tenants' employees)
- nobody can decide their own request
- the approval row is locked (`FOR UPDATE`) while deciding, so concurrent decisions serialise
- deciding the same way twice replays the result; deciding the opposite way is a conflict
- a request expires after 24 h and can no longer be approved
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.agent.executor import ToolOutcome, execute_once, invalid_arguments_result
from app.agent.runner_types import SessionScope
from app.agent.tools import Tool, ToolContext, ToolRegistry
from app.db.models import (
    Approval,
    ApprovalStatus,
    AuditLog,
    Employee,
    Message,
    MessageRole,
)
from app.llm.base import ToolCall

APPROVAL_TTL = timedelta(hours=24)


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)  # columns are timezone-naive UTC


# --------------------------------------------------------------------------- agent side


async def handle_call(ctx: ToolContext, registry: ToolRegistry, call: ToolCall) -> ToolOutcome:
    """Run a tool call, or park it for approval if the tool needs one."""
    tool = registry.get(call.name)
    if tool is not None and tool.requires_approval:
        return await request_approval(ctx, tool, call)
    return await execute_once(ctx, registry, call)


def _pending_view(approval: Approval, *, already_pending: bool = False) -> dict:
    view: dict = {"approval_id": str(approval.id)}
    if approval.status == ApprovalStatus.pending:
        view["status"] = "pending_approval"
        view["message"] = (
            "Sent to a human support agent for approval. Tell the employee it is pending; "
            "do not say it was done."
        )
    elif approval.status == ApprovalStatus.approved:
        view["status"] = "approved"
        view["result"] = approval.result
    else:
        view["status"] = approval.status.value
        view["message"] = "A support agent did not approve this request."
    if already_pending:
        view["already_pending"] = True
    return view


async def request_approval(ctx: ToolContext, tool: Tool, call: ToolCall) -> ToolOutcome:
    try:
        args = tool.args_model.model_validate_json(call.arguments or "{}")
    except ValidationError as exc:
        return ToolOutcome(result=invalid_arguments_result(exc), error="invalid arguments")
    normalized = args.model_dump_json()

    same_call = select(Approval).where(
        Approval.conversation_id == ctx.conversation_id, Approval.tool_call_id == call.id
    )
    existing = await ctx.session.scalar(same_call)
    if existing is not None:
        return ToolOutcome(result=_pending_view(existing), error=None, replayed=True)

    # The model may ask again with a new call id for the same thing: reuse the pending request.
    duplicate = await ctx.session.scalar(
        select(Approval).where(
            Approval.conversation_id == ctx.conversation_id,
            Approval.tool_name == call.name,
            Approval.arguments == normalized,
            Approval.status == ApprovalStatus.pending,
        )
    )
    if duplicate is not None:
        return ToolOutcome(result=_pending_view(duplicate, already_pending=True), error=None)

    created = await ctx.session.scalar(
        pg_insert(Approval)
        .values(
            tenant_id=ctx.tenant_id,
            conversation_id=ctx.conversation_id,
            requested_by=ctx.employee_id,
            tool_call_id=call.id,
            tool_name=call.name,
            arguments=normalized,
            status=ApprovalStatus.pending,
            expires_at=_utcnow() + APPROVAL_TTL,
        )
        .on_conflict_do_nothing(index_elements=["tenant_id", "conversation_id", "tool_call_id"])
        .returning(Approval.id)
    )
    approval = await ctx.session.scalar(same_call)
    if created is not None:
        ctx.session.add(
            AuditLog(
                tenant_id=ctx.tenant_id,
                actor_id=ctx.employee_id,
                actor_type="agent",
                action="approval.requested",
                subject=str(approval.id),
                details={"tool": call.name, "arguments": normalized},
            )
        )
    return ToolOutcome(result=_pending_view(approval), error=None)


# ---------------------------------------------------------------------------- human side


class ApprovalError(Exception):
    status_code = 400

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class ApprovalNotFound(ApprovalError):
    status_code = 404


class ApprovalForbidden(ApprovalError):
    status_code = 403


class ApprovalConflict(ApprovalError):
    status_code = 409


@dataclass(frozen=True)
class Decision:
    approval_id: uuid.UUID
    outcome: Literal["approved", "rejected", "expired"]
    replayed: bool = False
    result: dict | None = None


async def decide(
    *,
    scope: SessionScope,
    registry: ToolRegistry,
    approval_id: uuid.UUID,
    approver_id: uuid.UUID,
    decision: Literal["approve", "reject"],
    note: str | None = None,
) -> Decision:
    async with scope() as session:
        approval = await session.scalar(
            select(Approval).where(Approval.id == approval_id).with_for_update()
        )
        if approval is None:
            raise ApprovalNotFound("Approval not found")

        approver = await session.get(Employee, approver_id)
        if approver is None or not approver.is_support_agent:
            raise ApprovalForbidden("Only support agents can decide approvals.")
        if approver.id == approval.requested_by:
            raise ApprovalForbidden("Nobody can decide their own request.")

        wanted = ApprovalStatus.approved if decision == "approve" else ApprovalStatus.rejected
        if approval.status in (ApprovalStatus.approved, ApprovalStatus.rejected):
            if approval.status == wanted:
                return Decision(approval.id, approval.status.value, replayed=True, result=approval.result)
            raise ApprovalConflict(f"This request was already {approval.status.value}.")
        if approval.status == ApprovalStatus.expired:
            return Decision(approval.id, "expired", replayed=True)
        if _utcnow() > approval.expires_at:
            approval.status = ApprovalStatus.expired
            approval.decided_at = _utcnow()
            return Decision(approval.id, "expired")

        approval.decided_by = approver.id
        approval.decision_note = note
        approval.decided_at = _utcnow()

        if decision == "reject":
            approval.status = ApprovalStatus.rejected
            reason = f": {note}" if note else "."
            text = f"Update: {approver.full_name} did not approve your request{reason}"
            result = None
        else:
            call = ToolCall(id=approval.tool_call_id, name=approval.tool_name, arguments=approval.arguments)
            ctx = ToolContext(
                session=session,
                tenant_id=approval.tenant_id,
                employee_id=approval.requested_by,
                conversation_id=approval.conversation_id,
            )
            outcome = await execute_once(ctx, registry, call)
            approval.status = ApprovalStatus.approved
            approval.result = outcome.result
            approval.error = outcome.error
            result = outcome.result
            who = f"Update: {approver.full_name} approved your request"
            if outcome.error or "error" in outcome.result:
                problem = outcome.result.get("error", "the action failed")
                text = f"{who}, but it could not be completed: {problem}"
            else:
                text = f"{who} and it has been carried out. {outcome.result.get('message', '')}".strip()

        session.add(
            Message(
                tenant_id=approval.tenant_id,
                conversation_id=approval.conversation_id,
                role=MessageRole.assistant,
                content=text,
            )
        )
        session.add(
            AuditLog(
                tenant_id=approval.tenant_id,
                actor_id=approver.id,
                actor_type="human",
                action=f"approval.{approval.status.value}",
                subject=str(approval.id),
                details={"tool": approval.tool_name, "note": note},
            )
        )
        return Decision(approval.id, approval.status.value, result=result)
