"""Tools that involve a human: escalating, and the two actions a human has to approve first.

`reset_password` and `grant_system_access` are marked `requires_approval`: the agent can only *ask*.
Nothing here runs until a support agent approves (see app/agent/approvals.py), and both are simulated:
they write an audit record instead of touching a real identity provider.
"""

import uuid

from pydantic import BaseModel, Field
from sqlalchemy import select

from app.agent.tools.base import Tool, ToolContext
from app.db.models import (
    AuditLog,
    Employee,
    Escalation,
    EscalationStatus,
    System,
    Ticket,
    TicketEvent,
    TicketPriority,
    TicketStatus,
)


class EscalateArgs(BaseModel):
    ticket_id: uuid.UUID = Field(
        description="Id of one of the employee's own tickets (from create_ticket or list_my_tickets)."
    )
    reason: str = Field(min_length=10, max_length=500, description="Why a human needs to look at it.")
    urgency: TicketPriority = Field(default=TicketPriority.medium)


async def escalate_to_human(ctx: ToolContext, args: EscalateArgs) -> dict:
    ticket = await ctx.session.scalar(
        select(Ticket).where(Ticket.id == args.ticket_id, Ticket.employee_id == ctx.employee_id)
    )
    if ticket is None:
        return {"error": "No such ticket for this employee. Create the ticket first."}

    open_escalation = await ctx.session.scalar(
        select(Escalation).where(
            Escalation.ticket_id == ticket.id, Escalation.status != EscalationStatus.resolved
        )
    )
    if open_escalation is not None:
        return {
            "escalation_id": str(open_escalation.id),
            "ticket_id": str(ticket.id),
            "status": open_escalation.status.value,
            "already_escalated": True,
        }

    escalation = Escalation(
        tenant_id=ctx.tenant_id, ticket_id=ticket.id, reason=args.reason, urgency=args.urgency
    )
    ctx.session.add(escalation)
    ticket.status = TicketStatus.escalated
    await ctx.session.flush()
    ctx.session.add(
        TicketEvent(
            tenant_id=ctx.tenant_id,
            ticket_id=ticket.id,
            event_type="escalated",
            payload={"escalation_id": str(escalation.id), "urgency": args.urgency.value, "source": "agent"},
        )
    )
    await ctx.session.flush()
    return {
        "escalation_id": str(escalation.id),
        "ticket_id": str(ticket.id),
        "status": escalation.status.value,
        "message": "The ticket is now in the human support queue.",
    }


class ResetPasswordArgs(BaseModel):
    reason: str = Field(
        min_length=5, max_length=300, description="Why the reset is needed, e.g. forgotten password."
    )


async def reset_password(ctx: ToolContext, args: ResetPasswordArgs) -> dict:
    employee = await ctx.session.get(Employee, ctx.employee_id)
    ctx.session.add(
        AuditLog(
            tenant_id=ctx.tenant_id,
            actor_type="system",
            action="password_reset",
            subject=str(employee.id),
            details={"email": employee.email, "reason": args.reason, "simulated": True},
        )
    )
    await ctx.session.flush()
    return {
        "status": "reset_link_sent",
        "message": f"A one-time password reset link was sent to {employee.email} (simulated).",
    }


class GrantAccessArgs(BaseModel):
    system_name: str = Field(description="Internal system the employee needs access to, e.g. 'CRM'.")
    justification: str = Field(min_length=10, max_length=300, description="Business reason for the access.")


async def grant_system_access(ctx: ToolContext, args: GrantAccessArgs) -> dict:
    systems = (await ctx.session.scalars(select(System).order_by(System.name))).all()
    wanted = args.system_name.strip().lower()
    system = next((s for s in systems if s.name.lower() == wanted), None)
    if system is None:
        return {"error": f"Unknown system '{args.system_name}'.", "known_systems": [s.name for s in systems]}
    employee = await ctx.session.get(Employee, ctx.employee_id)
    ctx.session.add(
        AuditLog(
            tenant_id=ctx.tenant_id,
            actor_type="system",
            action="access_granted",
            subject=str(employee.id),
            details={"system": system.name, "justification": args.justification, "simulated": True},
        )
    )
    await ctx.session.flush()
    return {
        "status": "access_granted",
        "system": system.name,
        "message": f"Access to {system.name} was granted to {employee.email} (simulated).",
    }


SENSITIVE_TOOLS = [
    Tool(
        name="escalate_to_human",
        description=(
            "Put one of the employee's tickets in the human support queue. Use it when the employee asks "
            "for a person, or the problem is urgent and beyond what you can do. The ticket must exist."
        ),
        args_model=EscalateArgs,
        handler=escalate_to_human,
    ),
    Tool(
        name="reset_password",
        description=(
            "Request a password reset for the employee you are talking to. It does NOT happen "
            "immediately: a human support agent must approve it first."
        ),
        args_model=ResetPasswordArgs,
        handler=reset_password,
        requires_approval=True,
    ),
    Tool(
        name="grant_system_access",
        description=(
            "Request access to an internal system for the employee. It does NOT happen immediately: "
            "a human support agent must approve it first."
        ),
        args_model=GrantAccessArgs,
        handler=grant_system_access,
        requires_approval=True,
    ),
]
