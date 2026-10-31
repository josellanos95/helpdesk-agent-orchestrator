from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.agent.tools.base import IN_EMPLOYEE_LANGUAGE, Tool, ToolContext
from app.db.models import System, Ticket, TicketCategory, TicketEvent, TicketPriority, TicketStatus


class CheckSystemStatusArgs(BaseModel):
    system_name: str = Field(description="Name of the internal system, e.g. 'VPN', 'Email', 'CRM'.")


async def check_system_status(ctx: ToolContext, args: CheckSystemStatusArgs) -> dict:
    # No tenant filter on purpose: Row Level Security already limits this to the caller's tenant.
    systems = (await ctx.session.scalars(select(System).order_by(System.name))).all()
    wanted = args.system_name.strip().lower()
    for system in systems:
        if system.name.lower() == wanted:
            return {
                "system": system.name,
                "status": system.status.value,
                "last_updated": system.updated_at.isoformat(),
            }
    return {"error": f"Unknown system '{args.system_name}'.", "known_systems": [s.name for s in systems]}


class CreateTicketArgs(BaseModel):
    category: TicketCategory
    subject: str = Field(
        min_length=5, max_length=120, description=f"One-line summary. {IN_EMPLOYEE_LANGUAGE}"
    )
    description: str = Field(
        min_length=10,
        max_length=2000,
        description=f"What happened and what was tried. {IN_EMPLOYEE_LANGUAGE}",
    )
    priority: TicketPriority = Field(
        default=TicketPriority.medium,
        description="urgent only if work is fully blocked right now; high if a deadline is at risk.",
    )


async def create_ticket(ctx: ToolContext, args: CreateTicketArgs) -> dict:
    ticket = Ticket(
        tenant_id=ctx.tenant_id,
        conversation_id=ctx.conversation_id,
        employee_id=ctx.employee_id,
        category=args.category,
        subject=args.subject,
        description=args.description,
        priority=args.priority,
        status=TicketStatus.open,
    )
    ctx.session.add(ticket)
    await ctx.session.flush()
    ctx.session.add(
        TicketEvent(
            tenant_id=ctx.tenant_id,
            ticket_id=ticket.id,
            event_type="created",
            payload={"source": "agent", "priority": args.priority.value, "category": args.category.value},
        )
    )
    await ctx.session.flush()
    return {
        "ticket_id": str(ticket.id),
        "status": ticket.status.value,
        "priority": ticket.priority.value,
        "category": ticket.category.value,
    }


class ListMyTicketsArgs(BaseModel):
    include_closed: bool = Field(default=False, description="Also return resolved and closed tickets.")


async def list_my_tickets(ctx: ToolContext, args: ListMyTicketsArgs) -> dict:
    query = select(Ticket).where(Ticket.employee_id == ctx.employee_id)
    if not args.include_closed:
        query = query.where(Ticket.status.notin_([TicketStatus.resolved, TicketStatus.closed]))
    tickets = (await ctx.session.scalars(query.order_by(Ticket.created_at.desc()).limit(10))).all()
    total = await ctx.session.scalar(
        select(func.count()).select_from(Ticket).where(Ticket.employee_id == ctx.employee_id)
    )
    return {
        "tickets": [
            {
                "ticket_id": str(t.id),
                "subject": t.subject,
                "category": t.category.value,
                "priority": t.priority.value,
                "status": t.status.value,
                "created_at": t.created_at.isoformat(),
            }
            for t in tickets
        ],
        "total_tickets_for_employee": total,
    }


HELPDESK_TOOLS = [
    Tool(
        name="check_system_status",
        description="Look up the current status (operational, degraded, outage) of one internal system.",
        args_model=CheckSystemStatusArgs,
        handler=check_system_status,
    ),
    Tool(
        name="create_ticket",
        description=(
            "Open a support ticket for the employee you are talking to. Use it when the problem is not "
            "solved in this conversation. Do not create a second ticket for the same problem."
        ),
        args_model=CreateTicketArgs,
        handler=create_ticket,
    ),
    Tool(
        name="list_my_tickets",
        description="List the current employee's own tickets (open ones by default).",
        args_model=ListMyTicketsArgs,
        handler=list_my_tickets,
    ),
]
