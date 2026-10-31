"""Runs eval cases against the real agent, the real tools and a real database.

Nothing here is mocked except, optionally, the model (tests pass a scripted one). A run builds throwaway
copies of the demo companies (employees, systems and knowledge base, embedded with the configured
embedder), plays each case with a brand-new employee so cases cannot see each other's tickets, and
deletes the throwaway tenants at the end. The demo data is never touched.

Spending is bounded: a `Budget` stops new runs once the cap is reached (a run already in flight finishes,
so the final number can exceed the cap by one run).
"""

import asyncio
import json
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import delete, select

from app.agent.runner import run_agent
from app.agent.tools import ToolRegistry, default_registry
from app.db.models import (
    AgentRun,
    AgentStep,
    Approval,
    AuditLog,
    Conversation,
    Employee,
    Escalation,
    Tenant,
    Ticket,
)
from app.db.session import AdminSessionLocal, tenant_session
from app.llm.base import LLMClient
from app.llm.embeddings import Embedder
from app.llm.pricing import embedding_cost_usd
from app.services import knowledge_base as kb
from evals import checks as c
from evals.cases import CASES, EXTRA_ARTICLES, Case
from evals.transcript import State, ToolRecord, Transcript, Turn
from scripts.kb_content import ARTICLES
from scripts.seed_demo_data import DEMO_TENANTS

SLUG_PREFIX = "eval-"

# Held by every case, on top of its own checks.
DEFAULT_CHECKS = (c.completed(), c.no_internal_ids())


class Budget:
    def __init__(self, max_usd: Decimal) -> None:
        self.max_usd = max_usd
        self.spent = Decimal(0)

    def add(self, usd: Decimal) -> None:
        self.spent += usd

    @property
    def exhausted(self) -> bool:
        return self.spent >= self.max_usd


@dataclass
class World:
    """Throwaway tenants cloned from the demo ones."""

    tenants: dict[str, uuid.UUID] = field(default_factory=dict)  # demo slug -> throwaway tenant id
    setup_cost: Decimal = Decimal(0)  # embedding the knowledge base

    @classmethod
    async def create(cls, embedder: Embedder, slugs: set[str]) -> "World":
        world = cls()
        suffix = uuid.uuid4().hex[:8]
        try:
            for spec in DEMO_TENANTS:
                if spec["slug"] not in slugs:
                    continue
                async with AdminSessionLocal() as admin:
                    tenant = Tenant(name=spec["name"], slug=f"{SLUG_PREFIX}{spec['slug']}-{suffix}")
                    admin.add(tenant)
                    await admin.flush()
                    from app.db.models import System

                    for name, status in spec["systems"]:
                        admin.add(System(tenant_id=tenant.id, name=name, status=status))
                    await admin.commit()
                    world.tenants[spec["slug"]] = tenant.id
                await world._load_knowledge_base(embedder, spec["slug"])
        except BaseException:
            await world.close()
            raise
        return world

    async def _load_knowledge_base(self, embedder: Embedder, slug: str) -> None:
        tenant_id = self.tenants[slug]
        for title, body in [*ARTICLES.get(slug, []), *EXTRA_ARTICLES.get(slug, [])]:
            prepared = await kb.prepare_article(embedder, title, body)
            self.setup_cost += embedding_cost_usd(embedder.model, f"{title}\n{body}")
            async with tenant_session(tenant_id) as session:
                await kb.create_article(session, tenant_id, None, prepared)

    async def new_employee(self, slug: str, local_part: str) -> uuid.UUID:
        """A fresh copy of a demo employee, so a case starts with no tickets or requests."""
        spec = next(t for t in DEMO_TENANTS if t["slug"] == slug)
        name, email, title, is_support = next(
            e for e in spec["employees"] if e[1].startswith(local_part + "@")
        )
        async with AdminSessionLocal() as admin:
            employee = Employee(
                tenant_id=self.tenants[slug],
                full_name=name,
                email=email,
                job_title=title,
                is_support_agent=is_support,
            )
            admin.add(employee)
            await admin.commit()
            return employee.id

    async def close(self) -> None:
        if not self.tenants:
            return
        async with AdminSessionLocal() as admin:
            await admin.execute(delete(Tenant).where(Tenant.id.in_(list(self.tenants.values()))))
            await admin.commit()
        self.tenants.clear()


async def delete_stale_tenants() -> int:
    """Remove throwaway tenants left behind by a run that was killed."""
    async with AdminSessionLocal() as admin:
        result = await admin.execute(delete(Tenant).where(Tenant.slug.like(f"{SLUG_PREFIX}%")))
        await admin.commit()
        return result.rowcount or 0


# ---------------------------------------------------------------------------------- one case run


async def _state(tenant_id: uuid.UUID, employee_id: uuid.UUID) -> State:
    async with tenant_session(tenant_id) as session:
        tickets = list(
            await session.scalars(
                select(Ticket).where(Ticket.employee_id == employee_id).order_by(Ticket.created_at)
            )
        )
        approvals = list(await session.scalars(select(Approval).where(Approval.requested_by == employee_id)))
        escalations = list(
            await session.scalars(
                select(Escalation)
                .join(Ticket, Escalation.ticket_id == Ticket.id)
                .where(Ticket.employee_id == employee_id)
            )
        )
        audit = list(
            await session.scalars(select(AuditLog.action).where(AuditLog.subject == str(employee_id)))
        )
    return State(
        tickets=[
            {
                "id": str(t.id),
                "subject": t.subject,
                "priority": t.priority.value,
                "category": t.category.value,
                "status": t.status.value,
            }
            for t in tickets
        ],
        approvals=[{"tool": a.tool_name, "status": a.status.value} for a in approvals],
        escalations=[{"urgency": e.urgency.value, "status": e.status.value} for e in escalations],
        audit=audit,
    )


def _arguments(raw: object) -> dict:
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


async def _trace(tenant_id: uuid.UUID, run_id: uuid.UUID) -> tuple[list[ToolRecord], int, float, str | None]:
    async with tenant_session(tenant_id) as session:
        steps = list(
            await session.scalars(
                select(AgentStep).where(AgentStep.run_id == run_id).order_by(AgentStep.step_index)
            )
        )
        run = await session.get(AgentRun, run_id)
    tools = [
        ToolRecord(s.name, _arguments((s.input or {}).get("arguments")), s.output, s.error)
        for s in steps
        if s.kind == "tool"
    ]
    llm = [s for s in steps if s.kind == "llm"]
    return tools, len(llm), sum(s.latency_ms for s in llm) / 1000, run.error if run else None


async def play(
    case: Case,
    *,
    world: World,
    llm: LLMClient,
    embedder: Embedder,
    registry: ToolRegistry,
    max_steps: int,
) -> Transcript:
    tenant_id = world.tenants[case.tenant]
    employee_id = await world.new_employee(case.tenant, case.employee)
    async with tenant_session(tenant_id) as session:
        conversation = Conversation(tenant_id=tenant_id, employee_id=employee_id)
        session.add(conversation)
        await session.flush()
        conversation_id = conversation.id

    turns: list[Turn] = []
    for text in case.turns:
        started = time.perf_counter()
        try:
            result = await run_agent(
                scope=lambda: tenant_session(tenant_id),
                llm=llm,
                registry=registry,
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                employee_id=employee_id,
                user_text=text,
                max_steps=max_steps,
                embedder=embedder,
            )
        except Exception as exc:
            turns.append(
                Turn(text, "", "error", [], 0, 0, 0, Decimal(0), time.perf_counter() - started, 0.0,
                     await _state(tenant_id, employee_id), error=f"{type(exc).__name__}: {exc}"[:300])
            )  # fmt: skip
            break
        seconds = time.perf_counter() - started
        tools, llm_calls, llm_seconds, run_error = await _trace(tenant_id, result.run_id)
        turns.append(
            Turn(
                user=text,
                reply=result.reply,
                status=result.status.value,
                tools=tools,
                llm_calls=llm_calls,
                prompt_tokens=result.prompt_tokens,
                completion_tokens=result.completion_tokens,
                cost_usd=result.cost_usd,
                seconds=seconds,
                llm_seconds=llm_seconds,
                state=await _state(tenant_id, employee_id),
                error=run_error,
            )
        )
    return Transcript(case.id, llm.model, turns)


def grade(case: Case, transcript: Transcript) -> list[tuple[str, str]]:
    """(check name, what went wrong) for every check that failed."""
    failures = []
    for check in (*DEFAULT_CHECKS, *case.checks):
        try:
            problem = check(transcript)
        except Exception as exc:  # a check that cannot run is a failure, not a crash
            problem = f"check raised {type(exc).__name__}: {exc}"
        if problem:
            failures.append((check.name, problem))
    return failures


# ---------------------------------------------------------------------------------- a whole suite


@dataclass
class Outcome:
    case_id: str
    repeat: int
    transcript: Transcript | None
    failures: list[tuple[str, str]]
    skipped: bool = False

    @property
    def passed(self) -> bool:
        return not self.skipped and not self.failures


async def run_suite(
    *,
    llm: LLMClient,
    embedder: Embedder,
    cases: list[Case] | None = None,
    repeat: int = 1,
    concurrency: int = 4,
    budget: Budget,
    max_steps: int = 6,
    on_done: Callable[[Outcome], None] | None = None,
) -> tuple[list[Outcome], Decimal]:
    """Play every case `repeat` times. Returns the outcomes and the knowledge-base setup cost."""
    chosen = list(cases or CASES)
    world = await World.create(embedder, {case.tenant for case in chosen})
    budget.add(world.setup_cost)
    registry = default_registry()
    gate = asyncio.Semaphore(concurrency)
    outcomes: list[Outcome] = []

    async def one(case: Case, n: int) -> None:
        async with gate:
            if budget.exhausted:
                outcome = Outcome(
                    case.id, n, None, [("budget", "spend cap reached before this run")], skipped=True
                )
            else:
                transcript = await play(
                    case, world=world, llm=llm, embedder=embedder, registry=registry, max_steps=max_steps
                )
                budget.add(sum((t.cost_usd for t in transcript.turns), Decimal(0)))
                outcome = Outcome(case.id, n, transcript, grade(case, transcript))
        outcomes.append(outcome)
        if on_done:
            on_done(outcome)

    try:
        await asyncio.gather(*(one(case, n) for n in range(repeat) for case in chosen))
    finally:
        await world.close()
    outcomes.sort(key=lambda o: ([x.id for x in chosen].index(o.case_id), o.repeat))
    return outcomes, world.setup_cost
