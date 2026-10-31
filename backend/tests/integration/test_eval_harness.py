"""The eval harness against the real database with a scripted model: it must record what happened, grade it
correctly in both directions, spend within its cap and leave nothing behind. No network, no cost."""

from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.db.models import Tenant
from app.db.session import AdminSessionLocal
from app.llm.embeddings import HashingEmbedder
from evals.cases import CASES
from evals.harness import SLUG_PREFIX, Budget, delete_stale_tenants, run_suite
from tests.fakes import ScriptedLLM, call, say

CASE = next(c for c in CASES if c.id == "password_reset_waits_for_approval")
GREETING = next(c for c in CASES if c.id == "greeting_costs_one_call")


async def leftover_tenants() -> int:
    async with AdminSessionLocal() as admin:
        return await admin.scalar(
            select(func.count()).select_from(Tenant).where(Tenant.slug.like(f"{SLUG_PREFIX}%"))
        )


async def play(case, *responses):
    llm = ScriptedLLM(*responses)
    outcomes, _ = await run_suite(
        llm=llm, embedder=HashingEmbedder(), cases=[case], budget=Budget(Decimal("1"))
    )
    return outcomes[0], llm


async def test_a_good_run_passes_and_is_recorded():
    outcome, _ = await play(
        CASE,
        call("reset_password", {"reason": "forgotten password and lost phone"}),
        say("Your request is waiting for approval from a support agent."),
    )
    assert outcome.failures == []
    turn = outcome.transcript.turns[0]
    assert [t.name for t in turn.tools] == ["reset_password"]
    assert turn.llm_calls == 2
    assert turn.state.approvals == [{"tool": "reset_password", "status": "pending"}]
    assert turn.state.audit == []  # parked, not executed
    assert turn.cost_usd > 0


async def test_an_overclaiming_run_fails_for_the_right_reasons():
    outcome, _ = await play(CASE, say("Done! I've reset your password."))
    names = [name for name, _ in outcome.failures]
    assert "1 pending approval for reset_password" in names  # it never even asked
    assert "does not claim the reset happened" in names
    assert not outcome.passed


async def test_a_greeting_that_wanders_off_into_tools_fails():
    outcome, _ = await play(
        GREETING,
        call("list_my_tickets", {}),
        say("Hello!"),
    )
    names = [name for name, _ in outcome.failures]
    assert "calls no tools" in names
    assert "at most 1 model calls per turn" in names


async def test_a_model_error_is_graded_not_raised():
    outcome, _ = await play(GREETING, RuntimeError("upstream 500"))
    assert [name for name, _ in outcome.failures][0].startswith("the run completes")
    assert outcome.transcript.turns[0].status == "failed"


async def test_each_run_starts_with_a_fresh_employee():
    ticket_case = next(c for c in CASES if c.id == "ticket_for_broken_equipment")
    args = {
        "category": "hardware",
        "subject": "Cracked monitor",
        "description": "The monitor has a crack across the screen.",
    }
    llm = ScriptedLLM(
        call("create_ticket", args), say("Opened."), call("create_ticket", args), say("Opened.")
    )
    outcomes, _ = await run_suite(
        llm=llm, embedder=HashingEmbedder(), cases=[ticket_case], repeat=2, concurrency=1,
        budget=Budget(Decimal("1")),
    )  # fmt: skip
    # Both runs ended with exactly one ticket: the second did not inherit the first one's.
    assert [len(o.transcript.final.tickets) for o in outcomes] == [1, 1]


async def test_the_budget_stops_new_runs():
    llm = ScriptedLLM(say("Hello!"))
    outcomes, _ = await run_suite(
        llm=llm, embedder=HashingEmbedder(), cases=[GREETING], repeat=3, concurrency=1,
        budget=Budget(Decimal(0)),
    )  # fmt: skip
    assert all(o.skipped for o in outcomes)
    assert llm.calls == []


async def test_throwaway_tenants_are_always_removed():
    before = await leftover_tenants()
    await play(GREETING, say("Hello!"))
    assert await leftover_tenants() == before

    class BrokenEmbedder(HashingEmbedder):
        calls = 0

        async def embed(self, texts):
            BrokenEmbedder.calls += 1
            if BrokenEmbedder.calls > 2:  # fail halfway through loading the knowledge base
                raise RuntimeError("embedding service down")
            return await super().embed(texts)

    with pytest.raises(RuntimeError):
        await run_suite(
            llm=ScriptedLLM(), embedder=BrokenEmbedder(), cases=[GREETING], budget=Budget(Decimal("1"))
        )
    assert BrokenEmbedder.calls > 2
    assert await leftover_tenants() == before


async def test_stale_tenants_can_be_swept():
    async with AdminSessionLocal() as admin:
        admin.add(Tenant(name="Left behind", slug=f"{SLUG_PREFIX}stale-test"))
        await admin.commit()
    assert await delete_stale_tenants() >= 1
    assert await leftover_tenants() == 0
