"""The human side: approvals waiting for a decision and the escalation queue.

`approver_id` comes from the request body for now. Until real authentication exists (M8) any caller of a
tenant could claim to be any of its support agents; the checks below (support agent, not the requester)
are the rules the real identity will plug into.
"""

import json
import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.approvals import ApprovalError, decide
from app.agent.tools import ToolRegistry, default_registry
from app.api.deps import get_db, get_redis, get_tenant_id
from app.config import get_settings
from app.db.models import (
    Approval,
    ApprovalStatus,
    AuditLog,
    Employee,
    Escalation,
    EscalationStatus,
    Ticket,
    TicketEvent,
    TicketStatus,
)
from app.db.session import tenant_session
from app.services.locks import ConversationBusy, conversation_lock

router = APIRouter()


def get_registry() -> ToolRegistry:
    return default_registry()


# --------------------------------------------------------------------------- approvals


class ApprovalOut(BaseModel):
    id: uuid.UUID
    conversation_id: uuid.UUID
    requested_by: uuid.UUID
    requested_by_name: str
    tool_name: str
    arguments: dict
    status: ApprovalStatus
    decided_by: uuid.UUID | None
    decision_note: str | None
    result: dict | None
    created_at: datetime
    expires_at: datetime
    decided_at: datetime | None


class DecisionIn(BaseModel):
    decision: Literal["approve", "reject"]
    approver_id: uuid.UUID
    note: str | None = Field(default=None, max_length=500)


class DecisionOut(BaseModel):
    approval_id: uuid.UUID
    outcome: Literal["approved", "rejected", "expired"]
    replayed: bool
    result: dict | None


async def _approval_out(session: AsyncSession, approval: Approval) -> ApprovalOut:
    requester = await session.get(Employee, approval.requested_by)
    return ApprovalOut(
        id=approval.id,
        conversation_id=approval.conversation_id,
        requested_by=approval.requested_by,
        requested_by_name=requester.full_name if requester else "unknown",
        tool_name=approval.tool_name,
        arguments=json.loads(approval.arguments),
        status=approval.status,
        decided_by=approval.decided_by,
        decision_note=approval.decision_note,
        result=approval.result,
        created_at=approval.created_at,
        expires_at=approval.expires_at,
        decided_at=approval.decided_at,
    )


@router.get("/approvals", response_model=list[ApprovalOut])
async def list_approvals(
    status: ApprovalStatus | Literal["all"] = ApprovalStatus.pending, session: AsyncSession = Depends(get_db)
) -> list[ApprovalOut]:
    query = select(Approval).order_by(Approval.created_at)
    if status != "all":
        query = query.where(Approval.status == status)
    return [await _approval_out(session, a) for a in await session.scalars(query)]


@router.get("/approvals/{approval_id}", response_model=ApprovalOut)
async def get_approval(approval_id: uuid.UUID, session: AsyncSession = Depends(get_db)) -> ApprovalOut:
    approval = await session.get(Approval, approval_id)
    if approval is None:
        raise HTTPException(404, "Approval not found")
    return await _approval_out(session, approval)


@router.post("/approvals/{approval_id}/decision", response_model=DecisionOut)
async def decide_approval(
    approval_id: uuid.UUID,
    body: DecisionIn,
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    registry: ToolRegistry = Depends(get_registry),
    redis: Redis = Depends(get_redis),
) -> DecisionOut:
    async with tenant_session(tenant_id) as session:
        approval = await session.get(Approval, approval_id)
        if approval is None:
            raise HTTPException(404, "Approval not found")
        conversation_id = approval.conversation_id

    # Deciding appends a message to the conversation. If the agent is mid-run, that message would land
    # between a tool call and its result and break the history the model is sent, so wait our turn.
    try:
        async with conversation_lock(
            redis, tenant_id, conversation_id, ttl_seconds=get_settings().conversation_lock_ttl_seconds
        ):
            decision = await decide(
                scope=lambda: tenant_session(tenant_id),
                registry=registry,
                approval_id=approval_id,
                approver_id=body.approver_id,
                decision=body.decision,
                note=body.note,
            )
    except ConversationBusy as exc:
        raise HTTPException(409, "The conversation is being processed. Try again in a moment.") from exc
    except RedisError as exc:
        raise HTTPException(503, "The coordination service (Redis) is unavailable.") from exc
    except ApprovalError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc

    if decision.outcome == "expired":
        raise HTTPException(409, "This request expired and can no longer be decided.")
    return DecisionOut(
        approval_id=decision.approval_id,
        outcome=decision.outcome,
        replayed=decision.replayed,
        result=decision.result,
    )


# ------------------------------------------------------------------------- escalations


class EscalationOut(BaseModel):
    id: uuid.UUID
    ticket_id: uuid.UUID
    ticket_subject: str
    reason: str
    urgency: str
    status: EscalationStatus
    created_at: datetime
    resolved_at: datetime | None


class AgentActionIn(BaseModel):
    approver_id: uuid.UUID


async def _escalation_out(session: AsyncSession, escalation: Escalation) -> EscalationOut:
    ticket = await session.get(Ticket, escalation.ticket_id)
    return EscalationOut(
        id=escalation.id,
        ticket_id=escalation.ticket_id,
        ticket_subject=ticket.subject if ticket else "",
        reason=escalation.reason,
        urgency=escalation.urgency.value,
        status=escalation.status,
        created_at=escalation.created_at,
        resolved_at=escalation.resolved_at,
    )


@router.get("/escalations", response_model=list[EscalationOut])
async def list_escalations(
    status: EscalationStatus | Literal["open", "all"] = "open", session: AsyncSession = Depends(get_db)
) -> list[EscalationOut]:
    query = select(Escalation).order_by(Escalation.created_at)
    if status == "open":
        query = query.where(Escalation.status != EscalationStatus.resolved)
    elif status != "all":
        query = query.where(Escalation.status == status)
    return [await _escalation_out(session, e) for e in await session.scalars(query)]


async def _support_agent_or_403(session: AsyncSession, employee_id: uuid.UUID) -> Employee:
    agent = await session.get(Employee, employee_id)
    if agent is None or not agent.is_support_agent:
        raise HTTPException(403, "Only support agents can work the escalation queue.")
    return agent


async def _move_escalation(
    escalation_id: uuid.UUID, tenant_id: uuid.UUID, agent_id: uuid.UUID, target: EscalationStatus
) -> EscalationOut:
    async with tenant_session(tenant_id) as session:
        agent = await _support_agent_or_403(session, agent_id)
        escalation = await session.scalar(
            select(Escalation).where(Escalation.id == escalation_id).with_for_update()
        )
        if escalation is None:
            raise HTTPException(404, "Escalation not found")

        if escalation.status == target:
            return await _escalation_out(session, escalation)  # same action twice: nothing to do
        if escalation.status == EscalationStatus.resolved:
            raise HTTPException(409, "This escalation is already resolved.")
        if target == EscalationStatus.acknowledged and escalation.status != EscalationStatus.pending:
            raise HTTPException(409, f"Cannot acknowledge an escalation that is {escalation.status.value}.")

        ticket = await session.get(Ticket, escalation.ticket_id)
        escalation.status = target
        if target == EscalationStatus.acknowledged:
            ticket.status = TicketStatus.in_progress
        else:
            escalation.resolved_at = datetime.now(UTC).replace(tzinfo=None)
            ticket.status = TicketStatus.resolved
        session.add(
            TicketEvent(
                tenant_id=tenant_id,
                ticket_id=ticket.id,
                event_type=f"escalation_{target.value}",
                payload={"by": str(agent.id), "escalation_id": str(escalation.id)},
            )
        )
        session.add(
            AuditLog(
                tenant_id=tenant_id,
                actor_id=agent.id,
                actor_type="human",
                action=f"escalation.{target.value}",
                subject=str(escalation.id),
                details={"ticket_id": str(ticket.id)},
            )
        )
        await session.flush()
        return await _escalation_out(session, escalation)


@router.post("/escalations/{escalation_id}/acknowledge", response_model=EscalationOut)
async def acknowledge_escalation(
    escalation_id: uuid.UUID, body: AgentActionIn, tenant_id: uuid.UUID = Depends(get_tenant_id)
) -> EscalationOut:
    return await _move_escalation(escalation_id, tenant_id, body.approver_id, EscalationStatus.acknowledged)


@router.post("/escalations/{escalation_id}/resolve", response_model=EscalationOut)
async def resolve_escalation(
    escalation_id: uuid.UUID, body: AgentActionIn, tenant_id: uuid.UUID = Depends(get_tenant_id)
) -> EscalationOut:
    return await _move_escalation(escalation_id, tenant_id, body.approver_id, EscalationStatus.resolved)
