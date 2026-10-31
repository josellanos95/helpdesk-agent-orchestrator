"""Exactly-once tool execution (the tool_executions ledger)."""

import asyncio
import json

import pytest
from pydantic import BaseModel
from sqlalchemy import func, select

from app.agent.executor import execute_once
from app.agent.tools import Tool, ToolContext, ToolRegistry, default_registry
from app.db.models import Conversation, Ticket, ToolExecution
from app.db.session import AdminSessionLocal
from app.llm.base import ToolCall

pytestmark = pytest.mark.integration

TICKET_ARGS = json.dumps(
    {
        "category": "software",
        "subject": "CRM is very slow",
        "description": "Pages take over a minute to load since this morning.",
    }
)


async def run_call(as_tenant, tenant, conversation_id, call, registry=None):
    async with as_tenant(tenant.id) as session:
        ctx = ToolContext(
            session=session,
            tenant_id=tenant.id,
            employee_id=tenant.employee_id,
            conversation_id=conversation_id,
        )
        return await execute_once(ctx, registry or default_registry(), call)


async def count(model, **where):
    async with AdminSessionLocal() as session:
        query = select(func.count()).select_from(model)
        for key, value in where.items():
            query = query.where(getattr(model, key) == value)
        return await session.scalar(query)


async def test_the_same_call_id_runs_once_and_replays_the_stored_result(two_tenants, as_tenant):
    call = ToolCall(id="call_1", name="create_ticket", arguments=TICKET_ARGS)
    conversation_id = two_tenants.a.conversation_id

    first = await run_call(as_tenant, two_tenants.a, conversation_id, call)
    second = await run_call(as_tenant, two_tenants.a, conversation_id, call)

    assert (first.replayed, second.replayed) == (False, True)
    assert second.result == first.result  # same ticket id, not a new one
    assert await count(Ticket, conversation_id=conversation_id, subject="CRM is very slow") == 1
    assert await count(ToolExecution, conversation_id=conversation_id, tool_call_id="call_1") == 1


async def test_two_concurrent_attempts_at_the_same_call_create_one_ticket(two_tenants, as_tenant):
    call = ToolCall(id="call_race", name="create_ticket", arguments=TICKET_ARGS)
    conversation_id = two_tenants.a.conversation_id

    outcomes = await asyncio.gather(
        *[run_call(as_tenant, two_tenants.a, conversation_id, call) for _ in range(5)]
    )

    assert sorted(o.replayed for o in outcomes) == [False, True, True, True, True]
    assert len({o.result["ticket_id"] for o in outcomes}) == 1
    assert await count(Ticket, conversation_id=conversation_id, subject="CRM is very slow") == 1


async def test_a_failed_call_is_stored_too_and_not_retried(two_tenants, as_tenant):
    runs = {"n": 0}

    class NoArgs(BaseModel):
        pass

    async def flaky(ctx, args):
        runs["n"] += 1
        raise RuntimeError("boom")

    registry = ToolRegistry([Tool("flaky", "always fails", NoArgs, flaky)])
    call = ToolCall(id="call_fail", name="flaky", arguments="{}")
    conversation_id = two_tenants.a.conversation_id

    first = await run_call(as_tenant, two_tenants.a, conversation_id, call, registry)
    second = await run_call(as_tenant, two_tenants.a, conversation_id, call, registry)

    assert runs["n"] == 1
    assert first.error and second.error == first.error and second.replayed


async def test_the_same_call_id_in_another_conversation_runs_again(two_tenants, as_tenant):
    async with as_tenant(two_tenants.a.id) as session:
        other = Conversation(tenant_id=two_tenants.a.id, employee_id=two_tenants.a.employee_id)
        session.add(other)
        await session.flush()
        other_id = other.id
    call = ToolCall(id="call_same_id", name="create_ticket", arguments=TICKET_ARGS)

    a = await run_call(as_tenant, two_tenants.a, two_tenants.a.conversation_id, call)
    b = await run_call(as_tenant, two_tenants.a, other_id, call)

    assert not a.replayed and not b.replayed
    assert a.result["ticket_id"] != b.result["ticket_id"]


async def test_a_rolled_back_attempt_leaves_no_claim_behind(two_tenants, as_tenant):
    """Atomicity: if the transaction dies after the tool ran, the claim disappears with its effects,
    so a later attempt really executes instead of replaying a result that never committed."""
    call = ToolCall(id="call_rollback", name="create_ticket", arguments=TICKET_ARGS)
    conversation_id = two_tenants.a.conversation_id

    with pytest.raises(RuntimeError, match="crash after the tool"):
        async with as_tenant(two_tenants.a.id) as session:
            ctx = ToolContext(
                session=session,
                tenant_id=two_tenants.a.id,
                employee_id=two_tenants.a.employee_id,
                conversation_id=conversation_id,
            )
            await execute_once(ctx, default_registry(), call)
            raise RuntimeError("crash after the tool")

    assert await count(ToolExecution, tool_call_id="call_rollback") == 0
    assert await count(Ticket, conversation_id=conversation_id, subject="CRM is very slow") == 0

    retry = await run_call(as_tenant, two_tenants.a, conversation_id, call)
    assert not retry.replayed
    assert await count(Ticket, conversation_id=conversation_id, subject="CRM is very slow") == 1


async def test_the_ledger_is_tenant_scoped(two_tenants, as_tenant):
    from sqlalchemy import text

    async with as_tenant(two_tenants.b.id) as session:
        seen = (await session.execute(text("SELECT tenant_id FROM tool_executions"))).scalars().all()
    assert seen == [two_tenants.b.id]
