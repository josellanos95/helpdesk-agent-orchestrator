"""The agent loop against a real database and a scripted model."""

import json
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import func, select, text

from app.agent.runner import LLM_FAILED_REPLY, MAX_STEPS_REPLY, run_agent
from app.agent.tools import Tool, ToolRegistry, default_registry
from app.db.models import (
    AgentRun,
    AgentRunStatus,
    AgentStep,
    Conversation,
    Message,
    MessageRole,
    System,
    SystemStatus,
    Ticket,
    TicketEvent,
)
from app.db.session import AdminSessionLocal
from tests.fakes import ScriptedLLM, call, say

pytestmark = pytest.mark.integration


@pytest.fixture
async def world(two_tenants):
    """Tenant A has a degraded CRM; tenant B has a Mainframe that A must never see."""
    async with AdminSessionLocal() as session:
        session.add(System(tenant_id=two_tenants.a.id, name="CRM", status=SystemStatus.degraded))
        session.add(System(tenant_id=two_tenants.b.id, name="Mainframe", status=SystemStatus.outage))
        await session.commit()
    return two_tenants


async def converse(world, as_tenant, llm, text, *, conversation_id=None, registry=None, heartbeat=None, **kw):
    """One user turn as tenant A's employee. Returns (result, conversation_id)."""
    if conversation_id is None:
        async with as_tenant(world.a.id) as session:
            conversation = Conversation(tenant_id=world.a.id, employee_id=world.a.employee_id)
            session.add(conversation)
            await session.flush()
            conversation_id = conversation.id
    result = await run_agent(
        scope=lambda: as_tenant(world.a.id),
        llm=llm,
        registry=registry or default_registry(),
        tenant_id=world.a.id,
        conversation_id=conversation_id,
        employee_id=world.a.employee_id,
        user_text=text,
        heartbeat=heartbeat,
        **kw,
    )
    return result, conversation_id


async def stored(model, **where):
    async with AdminSessionLocal() as session:
        query = select(model)
        for key, value in where.items():
            query = query.where(getattr(model, key) == value)
        return list((await session.scalars(query)).all())


async def messages_of(conversation_id):
    async with AdminSessionLocal() as session:
        rows = await session.scalars(
            select(Message).where(Message.conversation_id == conversation_id).order_by(Message.seq)
        )
        return list(rows)


async def test_plain_answer_without_tools(world, as_tenant):
    llm = ScriptedLLM(say("Hello! How can I help?", tokens=(1000, 500)))
    result, conversation_id = await converse(world, as_tenant, llm, "hi")

    assert result.status == AgentRunStatus.completed
    assert result.reply == "Hello! How can I help?"
    assert (result.prompt_tokens, result.completion_tokens) == (1000, 500)
    assert result.cost_usd == Decimal("0.00125")
    assert [(m.role, m.content) for m in await messages_of(conversation_id)] == [
        (MessageRole.user, "hi"),
        (MessageRole.assistant, "Hello! How can I help?"),
    ]
    [run] = await stored(AgentRun, id=result.run_id)
    assert run.status == AgentRunStatus.completed and run.finished_at is not None
    assert run.cost_usd == Decimal("0.001250")


async def test_system_prompt_names_the_tenant_and_the_employee(world, as_tenant):
    llm = ScriptedLLM(say("ok"))
    await converse(world, as_tenant, llm, "hi")

    system = llm.calls[0]["messages"][0]
    assert system["role"] == "system"
    assert "Test a" in system["content"] and "Emp a" in system["content"]
    assert {t["function"]["name"] for t in llm.calls[0]["tools"]} == {
        "check_system_status",
        "create_ticket",
        "list_my_tickets",
        "escalate_to_human",
        "list_my_requests",
        "search_knowledge_base",
        "reset_password",
        "grant_system_access",
    }


async def test_tool_call_result_goes_back_to_the_model(world, as_tenant):
    llm = ScriptedLLM(call("check_system_status", {"system_name": "crm"}), say("The CRM is degraded."))
    result, conversation_id = await converse(world, as_tenant, llm, "CRM is slow")

    assert result.reply == "The CRM is degraded."
    assert [(m.role, m.tool_name) for m in await messages_of(conversation_id)] == [
        (MessageRole.user, None),
        (MessageRole.assistant, None),
        (MessageRole.tool, "check_system_status"),
        (MessageRole.assistant, None),
    ]

    # Second model call must see: user, assistant-with-tool_calls, tool result.
    replayed = llm.calls[1]["messages"][1:]
    assert [m["role"] for m in replayed] == ["user", "assistant", "tool"]
    assert replayed[1]["tool_calls"][0]["function"]["name"] == "check_system_status"
    assert replayed[2]["tool_call_id"] == replayed[1]["tool_calls"][0]["id"]
    assert json.loads(replayed[2]["content"])["status"] == "degraded"

    steps = await stored(AgentStep, run_id=result.run_id)
    assert [(s.kind, s.name) for s in sorted(steps, key=lambda s: s.step_index)] == [
        ("llm", "gpt-5-mini"),
        ("tool", "check_system_status"),
        ("llm", "gpt-5-mini"),
    ]


async def test_a_tool_cannot_see_another_tenants_systems(world, as_tenant):
    llm = ScriptedLLM(call("check_system_status", {"system_name": "Mainframe"}), say("Not found."))
    _, conversation_id = await converse(world, as_tenant, llm, "is the mainframe up?")

    tool_result = json.loads(llm.calls[1]["messages"][-1]["content"])
    assert "error" in tool_result
    assert "Mainframe" not in tool_result["known_systems"]  # B's system is invisible, even by name
    assert "CRM" in tool_result["known_systems"]


async def test_create_ticket_is_stored_for_the_right_employee_and_tenant(world, as_tenant):
    args = {
        "category": "software",
        "subject": "CRM is very slow",
        "description": "Pages take over a minute to load since this morning.",
        "priority": "high",
    }
    llm = ScriptedLLM(call("create_ticket", args), say("Ticket opened."))
    _, conversation_id = await converse(world, as_tenant, llm, "CRM is slow")

    [ticket] = await stored(Ticket, conversation_id=conversation_id)
    assert (ticket.tenant_id, ticket.employee_id) == (world.a.id, world.a.employee_id)
    assert ticket.subject == "CRM is very slow" and ticket.priority.value == "high"
    [event] = await stored(TicketEvent, ticket_id=ticket.id)
    assert event.event_type == "created" and event.payload["source"] == "agent"
    assert json.loads(llm.calls[1]["messages"][-1]["content"])["ticket_id"] == str(ticket.id)


async def test_invalid_arguments_are_reported_to_the_model_not_executed(world, as_tenant):
    bad = {"category": "teleportation", "subject": "x", "description": "y"}
    llm = ScriptedLLM(call("create_ticket", bad), say("Sorry, let me retry."))
    result, conversation_id = await converse(world, as_tenant, llm, "open a ticket")

    assert result.status == AgentRunStatus.completed
    assert await stored(Ticket, conversation_id=conversation_id) == []
    tool_result = json.loads(llm.calls[1]["messages"][-1]["content"])
    assert tool_result["error"] == "Invalid arguments."
    assert tool_result["details"]
    [tool_step] = [s for s in await stored(AgentStep, run_id=result.run_id) if s.kind == "tool"]
    assert tool_step.error == "invalid arguments"


async def test_malformed_json_arguments_do_not_crash_the_run(world, as_tenant):
    llm = ScriptedLLM(call("check_system_status", "{not json"), say("Hmm."))
    result, _ = await converse(world, as_tenant, llm, "status?")
    assert result.status == AgentRunStatus.completed
    assert json.loads(llm.calls[1]["messages"][-1]["content"])["error"] == "Invalid arguments."


async def test_unknown_tool_name_is_reported_to_the_model(world, as_tenant):
    llm = ScriptedLLM(call("delete_all_tickets", {}), say("I can't do that."))
    result, _ = await converse(world, as_tenant, llm, "wipe everything")
    assert result.status == AgentRunStatus.completed
    assert "Unknown tool" in json.loads(llm.calls[1]["messages"][-1]["content"])["error"]


async def test_failing_tool_is_rolled_back_alone_and_hides_internals(world, as_tenant):
    """A tool that writes and then blows up must leave no trace of its write, must not
    poison the surrounding transaction, and must not leak the exception text to the model."""
    from pydantic import BaseModel

    class NoArgs(BaseModel):
        pass

    async def explode(ctx, args):
        ctx.session.add(
            Ticket(
                tenant_id=ctx.tenant_id,
                employee_id=ctx.employee_id,
                category="other",
                subject="half-written",
                description="should be rolled back",
            )
        )
        await ctx.session.flush()
        raise RuntimeError("secret internal detail")

    async def db_error(ctx, args):
        # Foreign key violation: the *database* rejects it, which aborts the transaction
        # unless the tool ran inside a SAVEPOINT.
        ctx.session.add(
            Ticket(
                tenant_id=ctx.tenant_id,
                employee_id=uuid.uuid4(),
                category="other",
                subject="bad fk",
                description="employee does not exist",
            )
        )
        await ctx.session.flush()
        return {}

    registry = ToolRegistry(
        [
            Tool("explode", "always fails", NoArgs, explode),
            Tool("db_error", "database failure", NoArgs, db_error),
        ]
    )
    llm = ScriptedLLM(call("explode", {}), call("db_error", {}), say("Something went wrong, sorry."))
    result, conversation_id = await converse(world, as_tenant, llm, "do it", registry=registry)

    assert result.status == AgentRunStatus.completed
    assert await stored(Ticket, conversation_id=conversation_id) == []
    only_fixture = [t.subject for t in await stored(Ticket, tenant_id=world.a.id)]
    assert only_fixture == ["Subject a"]
    for model_call in llm.calls[1:]:
        assert "secret internal detail" not in json.dumps(model_call["messages"])
    # The conversation and trace were still saved after both failures.
    assert len(await messages_of(conversation_id)) == 6  # user + (assistant, tool) x2 + final
    errors = [s.error for s in await stored(AgentStep, run_id=result.run_id) if s.kind == "tool"]
    assert any("secret internal detail" in e for e in errors)  # kept in the trace for debugging


async def test_loop_stops_at_max_steps_instead_of_running_forever(world, as_tenant):
    llm = ScriptedLLM(*[call("check_system_status", {"system_name": "CRM"}) for _ in range(3)])
    result, conversation_id = await converse(world, as_tenant, llm, "loop", max_steps=3)

    assert result.status == AgentRunStatus.max_steps
    assert result.reply == MAX_STEPS_REPLY
    assert len(llm.calls) == 3
    last = (await messages_of(conversation_id))[-1]
    assert (last.role, last.content) == (MessageRole.assistant, MAX_STEPS_REPLY)


async def test_llm_outage_is_recorded_and_answered_gracefully(world, as_tenant):
    llm = ScriptedLLM(RuntimeError("api down"))
    result, conversation_id = await converse(world, as_tenant, llm, "hi")

    assert result.status == AgentRunStatus.failed
    assert result.reply == LLM_FAILED_REPLY
    [run] = await stored(AgentRun, id=result.run_id)
    assert run.status == AgentRunStatus.failed and "api down" in run.error
    [step] = await stored(AgentStep, run_id=result.run_id)
    assert step.kind == "llm" and "api down" in step.error
    assert [m.role for m in await messages_of(conversation_id)] == [MessageRole.user, MessageRole.assistant]


async def test_second_turn_sees_the_whole_conversation(world, as_tenant):
    first = ScriptedLLM(call("check_system_status", {"system_name": "CRM"}), say("CRM is degraded."))
    _, conversation_id = await converse(world, as_tenant, first, "CRM slow?")

    second = ScriptedLLM(say("You're welcome."))
    await converse(world, as_tenant, second, "thanks", conversation_id=conversation_id)

    roles = [m["role"] for m in second.calls[0]["messages"][1:]]
    assert roles == ["user", "assistant", "tool", "assistant", "user"]
    assert second.calls[0]["messages"][-1]["content"] == "thanks"


async def test_usage_and_cost_accumulate_over_every_model_call(world, as_tenant):
    llm = ScriptedLLM(
        call("check_system_status", {"system_name": "CRM"}, tokens=(1000, 100)),
        say("done", tokens=(1500, 200)),
    )
    result, _ = await converse(world, as_tenant, llm, "status")
    assert (result.prompt_tokens, result.completion_tokens) == (2500, 300)
    assert result.cost_usd == Decimal("0.001225")  # 2500*0.25/1e6 + 300*2/1e6


async def test_message_order_follows_the_conversation_across_transactions(world, as_tenant):
    llm = ScriptedLLM(
        call("check_system_status", {"system_name": "CRM"}),
        call("list_my_tickets", {}),
        say("done"),
    )
    _, conversation_id = await converse(world, as_tenant, llm, "go")
    rows = await messages_of(conversation_id)
    assert [m.role for m in rows] == [
        MessageRole.user,
        MessageRole.assistant,
        MessageRole.tool,
        MessageRole.assistant,
        MessageRole.tool,
        MessageRole.assistant,
    ]
    assert [m.seq for m in rows] == sorted(m.seq for m in rows)


async def test_seq_orders_messages_that_share_a_timestamp(world, as_tenant):
    """created_at is the transaction start time, so rows written in one transaction tie."""
    async with as_tenant(world.a.id) as session:
        conversation = Conversation(tenant_id=world.a.id, employee_id=world.a.employee_id)
        session.add(conversation)
        await session.flush()
        for n in range(3):
            session.add(
                Message(
                    tenant_id=world.a.id,
                    conversation_id=conversation.id,
                    role=MessageRole.user,
                    content=str(n),
                )
            )
    rows = await messages_of(conversation.id)
    assert len({m.created_at for m in rows}) == 1
    assert [m.content for m in rows] == ["0", "1", "2"]


async def test_run_and_steps_are_tenant_scoped_rows(world, as_tenant):
    llm = ScriptedLLM(say("hi"))
    result, _ = await converse(world, as_tenant, llm, "hi")
    [run] = await stored(AgentRun, id=result.run_id)
    assert run.tenant_id == world.a.id
    assert {s.tenant_id for s in await stored(AgentStep, run_id=result.run_id)} == {world.a.id}
    async with AdminSessionLocal() as session:
        b_runs = select(func.count()).select_from(AgentRun).where(AgentRun.tenant_id == world.b.id)
        assert await session.scalar(b_runs) == 1  # only the fixture's own; ours never touched B


# --- M4: transactions never span a model call -----------------------------------------------


class ProbingLLM(ScriptedLLM):
    """Counts the database transactions left open at the moment the model is being called."""

    def __init__(self, *responses):
        super().__init__(*responses)
        self.open_transactions: list[int] = []

    async def complete(self, *, messages, tools):
        self.open_transactions.append(await open_app_transactions())
        return await super().complete(messages=messages, tools=tools)


async def open_app_transactions() -> int:
    async with AdminSessionLocal() as session:
        return await session.scalar(
            text(
                "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() "
                "AND usename = 'app_runtime' AND state LIKE 'idle in transaction%'"
            )
        )


async def test_probe_can_see_an_open_transaction(world, as_tenant):
    """Guards the next test against passing vacuously."""
    async with as_tenant(world.a.id) as session:
        await session.execute(text("SELECT 1"))
        assert await open_app_transactions() >= 1


async def test_no_database_transaction_is_open_while_the_model_thinks(world, as_tenant):
    llm = ProbingLLM(call("check_system_status", {"system_name": "CRM"}), say("done"))
    await converse(world, as_tenant, llm, "status?")
    assert llm.open_transactions == [0, 0]


async def test_a_crash_midway_keeps_finished_steps_and_marks_the_run_failed(world, as_tenant, monkeypatch):
    args = {
        "category": "software",
        "subject": "CRM is very slow",
        "description": "Pages take over a minute to load since this morning.",
    }
    llm = ScriptedLLM(call("create_ticket", args), say("done"))

    import app.agent.runner as runner

    real_cost = runner.cost_usd
    calls = {"n": 0}

    def flaky_cost(model, usage):
        calls["n"] += 1
        if calls["n"] == 2:
            raise ValueError("bug while accounting the second model call")
        return real_cost(model, usage)

    monkeypatch.setattr(runner, "cost_usd", flaky_cost)

    async with as_tenant(world.a.id) as session:
        conversation = Conversation(tenant_id=world.a.id, employee_id=world.a.employee_id)
        session.add(conversation)
        await session.flush()
        conversation_id = conversation.id

    with pytest.raises(ValueError, match="second model call"):
        await converse(world, as_tenant, llm, "CRM is slow", conversation_id=conversation_id)

    [run] = await stored(AgentRun, conversation_id=conversation_id)
    assert run.status == AgentRunStatus.failed
    assert "ValueError" in run.error and run.finished_at is not None
    # The first step committed on its own: its ticket and messages are still there.
    assert len(await stored(Ticket, conversation_id=conversation_id)) == 1
    assert [m.role for m in await messages_of(conversation_id)] == [
        MessageRole.user,
        MessageRole.assistant,
        MessageRole.tool,
    ]


async def test_heartbeat_runs_before_every_model_call(world, as_tenant):
    beats = []

    async def heartbeat():
        beats.append(1)

    llm = ScriptedLLM(call("list_my_tickets", {}), say("done"))
    await converse(world, as_tenant, llm, "tickets?", heartbeat=heartbeat)
    assert len(beats) == 2


async def test_a_lost_lock_stops_the_run_and_marks_it_failed(world, as_tenant):
    from app.services.locks import LockLost

    beats = {"n": 0}

    async def heartbeat():
        beats["n"] += 1
        if beats["n"] == 2:
            raise LockLost("taken over")

    llm = ScriptedLLM(call("list_my_tickets", {}), say("never reached"))
    async with as_tenant(world.a.id) as session:
        conversation = Conversation(tenant_id=world.a.id, employee_id=world.a.employee_id)
        session.add(conversation)
        await session.flush()
        conversation_id = conversation.id
    with pytest.raises(LockLost):
        await converse(
            world, as_tenant, llm, "tickets?", conversation_id=conversation_id, heartbeat=heartbeat
        )

    assert len(llm.calls) == 1  # it did not race the new lock owner with a second model call
    [run] = await stored(AgentRun, conversation_id=conversation_id)
    assert run.status == AgentRunStatus.failed and "LockLost" in run.error
