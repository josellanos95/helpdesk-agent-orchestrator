"""Human approval of sensitive tool calls, at the service level (HTTP is in test_api_console)."""

import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select, update

from app.agent.approvals import (
    ApprovalConflict,
    ApprovalForbidden,
    ApprovalNotFound,
    decide,
    handle_call,
)
from app.agent.runner import run_agent
from app.agent.tools import ToolContext, default_registry
from app.db.models import (
    Approval,
    ApprovalStatus,
    AuditLog,
    Conversation,
    Escalation,
    Message,
    MessageRole,
    System,
    SystemStatus,
    Ticket,
    TicketCategory,
    TicketStatus,
    ToolExecution,
)
from app.db.session import AdminSessionLocal
from app.llm.base import ToolCall
from tests.fakes import ScriptedLLM, call, say

pytestmark = pytest.mark.integration

RESET = {"reason": "I forgot my password and cannot log in"}


async def new_conversation(as_tenant, tenant, employee_id=None) -> uuid.UUID:
    async with as_tenant(tenant.id) as session:
        conversation = Conversation(tenant_id=tenant.id, employee_id=employee_id or tenant.employee_id)
        session.add(conversation)
        await session.flush()
        return conversation.id


async def run_turn(as_tenant, tenant, llm, text, conversation_id, employee_id=None):
    return await run_agent(
        scope=lambda: as_tenant(tenant.id),
        llm=llm,
        registry=default_registry(),
        tenant_id=tenant.id,
        conversation_id=conversation_id,
        employee_id=employee_id or tenant.employee_id,
        user_text=text,
    )


async def request_reset(as_tenant, tenant, employee_id=None, args=None):
    """The agent asks for a password reset; returns (conversation_id, approval)."""
    conversation_id = await new_conversation(as_tenant, tenant, employee_id)
    llm = ScriptedLLM(call("reset_password", args or RESET), say("It is waiting for approval."))
    await run_turn(as_tenant, tenant, llm, "I forgot my password", conversation_id, employee_id)
    [approval] = await stored(Approval, conversation_id=conversation_id)
    return conversation_id, approval


async def stored(model, **where):
    async with AdminSessionLocal() as session:
        query = select(model)
        for key, value in where.items():
            query = query.where(getattr(model, key) == value)
        return list((await session.scalars(query)).all())


async def audit_count(tenant_id, action) -> int:
    async with AdminSessionLocal() as session:
        return await session.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.tenant_id == tenant_id, AuditLog.action == action)
        )


async def decide_as(as_tenant, tenant, approval_id, approver_id, decision="approve", note=None):
    return await decide(
        scope=lambda: as_tenant(tenant.id),
        registry=default_registry(),
        approval_id=approval_id,
        approver_id=approver_id,
        decision=decision,
        note=note,
    )


async def messages_of(conversation_id):
    async with AdminSessionLocal() as session:
        rows = await session.scalars(
            select(Message).where(Message.conversation_id == conversation_id).order_by(Message.seq)
        )
        return list(rows)


# ------------------------------------------------------------------ agent side: asking


async def test_a_sensitive_request_is_parked_and_nothing_runs(two_tenants, as_tenant):
    conversation_id, approval = await request_reset(as_tenant, two_tenants.a)

    assert approval.status == ApprovalStatus.pending
    assert approval.tool_name == "reset_password"
    assert json.loads(approval.arguments) == RESET
    assert approval.requested_by == two_tenants.a.employee_id
    assert await audit_count(two_tenants.a.id, "password_reset") == 0  # not executed
    assert await stored(ToolExecution, conversation_id=conversation_id) == []  # not even claimed
    assert await audit_count(two_tenants.a.id, "approval.requested") == 1


async def test_the_model_is_told_it_is_pending_not_done(two_tenants, as_tenant):
    conversation_id = await new_conversation(as_tenant, two_tenants.a)
    llm = ScriptedLLM(call("reset_password", RESET), say("Pending approval."))
    result = await run_turn(as_tenant, two_tenants.a, llm, "reset please", conversation_id)

    tool_message = json.loads(llm.calls[1]["messages"][-1]["content"])
    assert tool_message["status"] == "pending_approval"
    assert "do not say it was done" in tool_message["message"]
    assert result.reply == "Pending approval."


async def test_invalid_arguments_never_create_an_approval(two_tenants, as_tenant):
    conversation_id = await new_conversation(as_tenant, two_tenants.a)
    llm = ScriptedLLM(call("reset_password", {"reason": "x"}), say("Let me retry."))
    await run_turn(as_tenant, two_tenants.a, llm, "reset", conversation_id)

    assert await stored(Approval, conversation_id=conversation_id) == []
    assert json.loads(llm.calls[1]["messages"][-1]["content"])["error"] == "Invalid arguments."


async def test_the_same_tool_call_id_returns_the_same_approval(two_tenants, as_tenant):
    conversation_id = await new_conversation(as_tenant, two_tenants.a)
    tool_call = ToolCall(id="call_same", name="reset_password", arguments=json.dumps(RESET))
    outcomes = []
    for _ in range(2):
        async with as_tenant(two_tenants.a.id) as session:
            ctx = ToolContext(
                session=session,
                tenant_id=two_tenants.a.id,
                employee_id=two_tenants.a.employee_id,
                conversation_id=conversation_id,
            )
            outcomes.append(await handle_call(ctx, default_registry(), tool_call))

    assert outcomes[0].result["approval_id"] == outcomes[1].result["approval_id"]
    assert (outcomes[0].replayed, outcomes[1].replayed) == (False, True)
    assert len(await stored(Approval, conversation_id=conversation_id)) == 1


async def test_asking_again_with_a_new_call_id_reuses_the_pending_request(two_tenants, as_tenant):
    conversation_id = await new_conversation(as_tenant, two_tenants.a)
    llm = ScriptedLLM(
        call("reset_password", RESET),
        call("reset_password", RESET),  # the model repeats itself with a fresh call id
        say("Still pending."),
    )
    await run_turn(as_tenant, two_tenants.a, llm, "reset please", conversation_id)

    assert len(await stored(Approval, conversation_id=conversation_id)) == 1
    assert json.loads(llm.calls[2]["messages"][-1]["content"])["already_pending"] is True


async def test_a_different_request_gets_its_own_approval(two_tenants, as_tenant):
    conversation_id = await new_conversation(as_tenant, two_tenants.a)
    llm = ScriptedLLM(
        call("reset_password", RESET),
        call("reset_password", {"reason": "my account is also locked out"}),
        say("Two requests pending."),
    )
    await run_turn(as_tenant, two_tenants.a, llm, "reset please", conversation_id)
    assert len(await stored(Approval, conversation_id=conversation_id)) == 2


# ------------------------------------------------------------------ human side: deciding


async def test_approving_runs_the_action_once_and_tells_the_employee(two_tenants, support_agents, as_tenant):
    conversation_id, approval = await request_reset(as_tenant, two_tenants.a)

    decision = await decide_as(as_tenant, two_tenants.a, approval.id, support_agents["a"], note="ok")

    assert (decision.outcome, decision.replayed) == ("approved", False)
    assert await audit_count(two_tenants.a.id, "password_reset") == 1
    [stored_approval] = await stored(Approval, id=approval.id)
    assert stored_approval.status == ApprovalStatus.approved
    assert stored_approval.decided_by == support_agents["a"]
    assert stored_approval.result["status"] == "reset_link_sent"
    assert (
        len(await stored(ToolExecution, conversation_id=conversation_id, tool_call_id=approval.tool_call_id))
        == 1
    )

    last = (await messages_of(conversation_id))[-1]
    assert last.role == MessageRole.assistant
    assert "Agent a approved your request" in last.content and "reset link was sent" in last.content
    assert await audit_count(two_tenants.a.id, "approval.approved") == 1


async def test_deciding_the_same_way_twice_replays_and_does_not_run_again(
    two_tenants, support_agents, as_tenant
):
    _, approval = await request_reset(as_tenant, two_tenants.a)
    first = await decide_as(as_tenant, two_tenants.a, approval.id, support_agents["a"])
    second = await decide_as(as_tenant, two_tenants.a, approval.id, support_agents["a"])

    assert (first.replayed, second.replayed) == (False, True)
    assert second.result == first.result
    assert await audit_count(two_tenants.a.id, "password_reset") == 1


async def test_a_double_click_from_many_clients_executes_once(two_tenants, support_agents, as_tenant):
    _, approval = await request_reset(as_tenant, two_tenants.a)

    decisions = await asyncio.gather(
        *[decide_as(as_tenant, two_tenants.a, approval.id, support_agents["a"]) for _ in range(6)]
    )

    assert sorted(d.replayed for d in decisions) == [False] + [True] * 5
    assert await audit_count(two_tenants.a.id, "password_reset") == 1
    assert await audit_count(two_tenants.a.id, "approval.approved") == 1


async def test_opposite_decisions_conflict(two_tenants, support_agents, as_tenant):
    _, approved = await request_reset(as_tenant, two_tenants.a)
    await decide_as(as_tenant, two_tenants.a, approved.id, support_agents["a"], "approve")
    with pytest.raises(ApprovalConflict, match="already approved"):
        await decide_as(as_tenant, two_tenants.a, approved.id, support_agents["a"], "reject")

    _, rejected = await request_reset(as_tenant, two_tenants.a, args={"reason": "another request, different"})
    await decide_as(as_tenant, two_tenants.a, rejected.id, support_agents["a"], "reject")
    with pytest.raises(ApprovalConflict, match="already rejected"):
        await decide_as(as_tenant, two_tenants.a, rejected.id, support_agents["a"], "approve")
    assert await audit_count(two_tenants.a.id, "password_reset") == 1  # only the approved one


async def test_rejecting_runs_nothing_and_says_why(two_tenants, support_agents, as_tenant):
    conversation_id, approval = await request_reset(as_tenant, two_tenants.a)
    decision = await decide_as(
        as_tenant,
        two_tenants.a,
        approval.id,
        support_agents["a"],
        "reject",
        note="Use the self-service portal",
    )

    assert decision.outcome == "rejected"
    assert await audit_count(two_tenants.a.id, "password_reset") == 0
    assert await stored(ToolExecution, conversation_id=conversation_id) == []
    last = (await messages_of(conversation_id))[-1]
    assert "did not approve your request: Use the self-service portal" in last.content


async def test_only_support_agents_of_the_same_tenant_can_decide(two_tenants, support_agents, as_tenant):
    _, approval = await request_reset(as_tenant, two_tenants.a)

    with pytest.raises(ApprovalForbidden, match="Only support agents"):
        await decide_as(as_tenant, two_tenants.a, approval.id, two_tenants.a.employee_id)  # ordinary employee
    with pytest.raises(ApprovalForbidden, match="Only support agents"):
        await decide_as(as_tenant, two_tenants.a, approval.id, support_agents["b"])  # other tenant's agent
    with pytest.raises(ApprovalForbidden):
        await decide_as(as_tenant, two_tenants.a, approval.id, uuid.uuid4())  # nobody
    with pytest.raises(ApprovalNotFound):
        await decide_as(as_tenant, two_tenants.a, uuid.uuid4(), support_agents["a"])
    assert await audit_count(two_tenants.a.id, "password_reset") == 0


async def test_nobody_can_decide_their_own_request(two_tenants, support_agents, as_tenant):
    """A support agent who asks for something still needs someone else to approve it."""
    _, approval = await request_reset(as_tenant, two_tenants.a, employee_id=support_agents["a"])
    with pytest.raises(ApprovalForbidden, match="their own request"):
        await decide_as(as_tenant, two_tenants.a, approval.id, support_agents["a"])
    assert await audit_count(two_tenants.a.id, "password_reset") == 0


async def test_another_tenant_cannot_even_see_the_approval(two_tenants, support_agents, as_tenant):
    _, approval = await request_reset(as_tenant, two_tenants.a)
    with pytest.raises(ApprovalNotFound):
        await decide_as(as_tenant, two_tenants.b, approval.id, support_agents["b"])


async def test_an_expired_request_cannot_be_approved(two_tenants, support_agents, as_tenant):
    _, approval = await request_reset(as_tenant, two_tenants.a)
    async with AdminSessionLocal() as session:
        await session.execute(
            update(Approval)
            .where(Approval.id == approval.id)
            .values(expires_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=1))
        )
        await session.commit()

    decision = await decide_as(as_tenant, two_tenants.a, approval.id, support_agents["a"])
    again = await decide_as(as_tenant, two_tenants.a, approval.id, support_agents["a"], "reject")

    assert (decision.outcome, again.outcome) == ("expired", "expired")
    assert await audit_count(two_tenants.a.id, "password_reset") == 0
    [stored_approval] = await stored(Approval, id=approval.id)
    assert stored_approval.status == ApprovalStatus.expired


async def test_the_next_turn_sees_what_was_decided(two_tenants, support_agents, as_tenant):
    conversation_id, approval = await request_reset(as_tenant, two_tenants.a)
    await decide_as(as_tenant, two_tenants.a, approval.id, support_agents["a"])

    llm = ScriptedLLM(say("Glad it worked."))
    await run_turn(as_tenant, two_tenants.a, llm, "thanks, it worked", conversation_id)

    history = [m for m in llm.calls[0]["messages"] if m["role"] == "assistant" and m.get("content")]
    assert any("approved your request and it has been carried out" in m["content"] for m in history)


# ---------------------------------------------------------------- the other sensitive tool


async def test_granting_access_requires_approval_and_records_the_system(
    two_tenants, support_agents, as_tenant
):
    async with AdminSessionLocal() as session:
        session.add(System(tenant_id=two_tenants.a.id, name="CRM", status=SystemStatus.operational))
        await session.commit()
    conversation_id = await new_conversation(as_tenant, two_tenants.a)
    args = {"system_name": "crm", "justification": "I joined the sales team this week"}
    llm = ScriptedLLM(call("grant_system_access", args), say("Waiting for approval."))
    await run_turn(as_tenant, two_tenants.a, llm, "I need CRM access", conversation_id)
    assert await audit_count(two_tenants.a.id, "access_granted") == 0

    [approval] = await stored(Approval, conversation_id=conversation_id)
    await decide_as(as_tenant, two_tenants.a, approval.id, support_agents["a"])

    [entry] = [a for a in await stored(AuditLog, tenant_id=two_tenants.a.id) if a.action == "access_granted"]
    assert entry.details["system"] == "CRM"


async def test_approving_an_action_that_then_fails_says_so_instead_of_claiming_success(
    two_tenants, support_agents, as_tenant
):
    conversation_id = await new_conversation(as_tenant, two_tenants.a)
    args = {"system_name": "Mainframe9000", "justification": "I need it for the quarterly close"}
    llm = ScriptedLLM(call("grant_system_access", args), say("Waiting."))
    await run_turn(as_tenant, two_tenants.a, llm, "access please", conversation_id)
    [approval] = await stored(Approval, conversation_id=conversation_id)

    await decide_as(as_tenant, two_tenants.a, approval.id, support_agents["a"])

    last = (await messages_of(conversation_id))[-1]
    assert "could not be completed" in last.content and "Unknown system" in last.content
    assert await audit_count(two_tenants.a.id, "access_granted") == 0


# ---------------------------------------------------------------------- escalation tool


async def new_ticket(tenant) -> uuid.UUID:
    """A fresh ticket for the tenant's employee (the fixture's own ticket is already escalated)."""
    async with AdminSessionLocal() as session:
        ticket = Ticket(
            tenant_id=tenant.id,
            employee_id=tenant.employee_id,
            category=TicketCategory.network,
            subject="VPN is down",
            description="The VPN is down for the whole team since this morning.",
        )
        session.add(ticket)
        await session.flush()
        ticket_id = ticket.id
        await session.commit()
    return ticket_id


async def escalate(as_tenant, tenant, ticket_id, reason="The VPN is down for the whole team"):
    conversation_id = await new_conversation(as_tenant, tenant)
    llm = ScriptedLLM(
        call("escalate_to_human", {"ticket_id": str(ticket_id), "reason": reason, "urgency": "high"}),
        say("A human will review it."),
    )
    await run_turn(as_tenant, tenant, llm, "get me a human", conversation_id)
    return json.loads(llm.calls[1]["messages"][-1]["content"])


async def test_escalating_puts_the_ticket_in_the_human_queue(two_tenants, as_tenant):
    ticket_id = await new_ticket(two_tenants.a)
    result = await escalate(as_tenant, two_tenants.a, ticket_id)

    assert result["status"] == "pending" and "human support queue" in result["message"]
    [ticket] = await stored(Ticket, id=ticket_id)
    assert ticket.status == TicketStatus.escalated
    [escalation] = await stored(Escalation, ticket_id=ticket_id)
    assert escalation.reason == "The VPN is down for the whole team"
    assert escalation.urgency.value == "high"


async def test_escalating_twice_does_not_create_a_second_escalation(two_tenants, as_tenant):
    ticket_id = await new_ticket(two_tenants.a)
    await escalate(as_tenant, two_tenants.a, ticket_id)
    again = await escalate(as_tenant, two_tenants.a, ticket_id, reason="Still down, please hurry")

    assert again["already_escalated"] is True
    assert len(await stored(Escalation, ticket_id=ticket_id)) == 1


async def test_only_your_own_tickets_can_be_escalated(two_tenants, as_tenant):
    their_ticket_id = await new_ticket(two_tenants.b)
    other_tenants_ticket = await escalate(as_tenant, two_tenants.a, their_ticket_id)
    made_up = await escalate(as_tenant, two_tenants.a, uuid.uuid4())

    assert "No such ticket" in other_tenants_ticket["error"] and "No such ticket" in made_up["error"]
    assert await stored(Escalation, ticket_id=their_ticket_id) == []
    [their_ticket] = await stored(Ticket, id=their_ticket_id)
    assert their_ticket.status != TicketStatus.escalated


async def test_a_colleagues_ticket_in_the_same_tenant_cannot_be_escalated(
    two_tenants, support_agents, as_tenant
):
    """RLS keeps tenants apart, but inside a tenant the tool itself must check ownership."""
    async with AdminSessionLocal() as session:
        ticket = Ticket(
            tenant_id=two_tenants.a.id,
            employee_id=support_agents["a"],  # somebody else's ticket
            category=TicketCategory.network,
            subject="Colleague's ticket",
            description="Not the employee who is chatting.",
        )
        session.add(ticket)
        await session.flush()
        colleague_ticket_id = ticket.id
        await session.commit()

    result = await escalate(as_tenant, two_tenants.a, colleague_ticket_id)

    assert "No such ticket" in result["error"]
    assert await stored(Escalation, ticket_id=colleague_ticket_id) == []


# ------------------------------------------------------------ asking about a request's status


async def my_requests(as_tenant, tenant, employee_id=None) -> dict[str, dict]:
    """What the model sees when it calls list_my_requests, keyed by approval id (the two_tenants
    fixture already gives every employee one pending approval, so tests look up their own)."""
    conversation_id = await new_conversation(as_tenant, tenant, employee_id)
    llm = ScriptedLLM(call("list_my_requests", {}), say("Here is the status."))
    await run_turn(as_tenant, tenant, llm, "did it go through?", conversation_id, employee_id)
    requests = json.loads(llm.calls[1]["messages"][-1]["content"])["requests"]
    return {r["approval_id"]: r for r in requests}


async def test_the_model_can_look_up_the_real_status_of_a_request(two_tenants, support_agents, as_tenant):
    _, approval = await request_reset(as_tenant, two_tenants.a)
    key = str(approval.id)

    pending = (await my_requests(as_tenant, two_tenants.a))[key]
    assert pending["status"] == "pending" and pending["request"] == "reset_password"
    assert pending["decided_by"] is None

    await decide_as(as_tenant, two_tenants.a, approval.id, support_agents["a"], note="checked by phone")

    approved = (await my_requests(as_tenant, two_tenants.a))[key]
    assert approved["status"] == "approved" and approved["decided_by"] == "Agent a"
    assert approved["note"] == "checked by phone" and "reset link was sent" in approved["outcome"]


async def test_a_rejected_request_shows_the_reason(two_tenants, support_agents, as_tenant):
    _, approval = await request_reset(as_tenant, two_tenants.a)
    await decide_as(as_tenant, two_tenants.a, approval.id, support_agents["a"], "reject", "Use self-service")

    rejected = (await my_requests(as_tenant, two_tenants.a))[str(approval.id)]
    assert (rejected["status"], rejected["note"]) == ("rejected", "Use self-service")


async def test_you_only_see_your_own_requests_never_a_colleagues_or_another_tenants(
    two_tenants, support_agents, as_tenant
):
    _, colleagues = await request_reset(as_tenant, two_tenants.a, employee_id=support_agents["a"])
    _, other_tenants = await request_reset(as_tenant, two_tenants.b)
    _, mine = await request_reset(as_tenant, two_tenants.a)

    seen = await my_requests(as_tenant, two_tenants.a)
    assert str(mine.id) in seen
    assert str(colleagues.id) not in seen
    assert str(other_tenants.id) not in seen
