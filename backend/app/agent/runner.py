"""The agent loop: model -> tool calls -> tool results -> model ... until it answers.

Transactions are short and never span a model call. Each step is its own tenant-scoped transaction
(see `tenant_session`), so a slow model holds no database connection, and a crash leaves every step
that finished committed:

    tx  create the run + user message
    loop:
      tx   read the history
           ...call the model (no transaction open)...
      tx   store the model step + assistant message + run its tool calls (exactly once each) + results
    tx  close the run (status, totals)

Every read and write still goes through Row Level Security, because `scope()` is a tenant session.
"""

import json
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.executor import execute_once
from app.agent.prompts import build_system_prompt
from app.agent.tools import ToolContext, ToolRegistry
from app.db.models import AgentRun, AgentRunStatus, AgentStep, Employee, Message, MessageRole, Tenant
from app.llm.base import LLMClient
from app.llm.pricing import cost_usd

logger = logging.getLogger(__name__)

DEFAULT_MAX_STEPS = 6
LLM_FAILED_REPLY = (
    "Sorry, I hit a problem on my side and could not finish your request. Nothing was changed "
    "by this attempt that I could confirm. Please try again in a moment."
)
MAX_STEPS_REPLY = (
    "I couldn't resolve this in a reasonable number of steps, so I stopped instead of guessing. "
    "Please try rephrasing, or ask for a human."
)

# Opens one short tenant-scoped transaction: `async with scope() as session: ...`
SessionScope = Callable[[], AbstractAsyncContextManager[AsyncSession]]
Heartbeat = Callable[[], Awaitable[None]]


@dataclass(frozen=True)
class AgentResult:
    run_id: uuid.UUID
    status: AgentRunStatus
    reply: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: Decimal


@dataclass
class _Totals:
    step_index: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost: Decimal = Decimal(0)
    error: str | None = None


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)  # columns are timezone-naive UTC


def _ms_since(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


async def _history(session: AsyncSession, conversation_id: uuid.UUID) -> list[dict]:
    rows = await session.scalars(
        select(Message).where(Message.conversation_id == conversation_id).order_by(Message.seq)
    )
    out: list[dict] = []
    for m in rows:
        if m.role == MessageRole.user:
            out.append({"role": "user", "content": m.content})
        elif m.role == MessageRole.assistant:
            msg: dict = {"role": "assistant", "content": m.content or None}
            if m.tool_calls:
                msg["tool_calls"] = [
                    {
                        "id": c["id"],
                        "type": "function",
                        "function": {"name": c["name"], "arguments": c["arguments"]},
                    }
                    for c in m.tool_calls
                ]
            out.append(msg)
        else:
            out.append({"role": "tool", "tool_call_id": m.tool_call_id, "content": m.content})
    return out


async def run_agent(
    *,
    scope: SessionScope,
    llm: LLMClient,
    registry: ToolRegistry,
    tenant_id: uuid.UUID,
    conversation_id: uuid.UUID,
    employee_id: uuid.UUID,
    user_text: str,
    max_steps: int = DEFAULT_MAX_STEPS,
    heartbeat: Heartbeat | None = None,
) -> AgentResult:
    async with scope() as session:
        tenant = await session.get(Tenant, tenant_id)  # the tenants table is not RLS-scoped
        employee = await session.get(Employee, employee_id)
        system_prompt = build_system_prompt(tenant, employee)
        run = AgentRun(tenant_id=tenant_id, conversation_id=conversation_id, model=llm.model)
        session.add(run)
        session.add(_message(tenant_id, conversation_id, MessageRole.user, user_text))
        await session.flush()
        run_id = run.id

    totals = _Totals()
    try:
        status, reply = await _loop(
            scope, llm, registry, tenant_id, conversation_id, employee_id,
            run_id, system_prompt, totals, max_steps, heartbeat,
        )  # fmt: skip
        await _close_run(scope, run_id, totals, status)
    except Exception as exc:
        # An unexpected bug, or a lost lock: leave the run marked failed instead of "running" forever.
        totals.error = f"{type(exc).__name__}: {exc}"[:500]
        try:
            await _close_run(scope, run_id, totals, AgentRunStatus.failed)
        except Exception:
            logger.exception("Could not mark run %s as failed", run_id)
        raise

    return AgentResult(
        run_id=run_id,
        status=status,
        reply=reply,
        prompt_tokens=totals.prompt_tokens,
        completion_tokens=totals.completion_tokens,
        cost_usd=totals.cost,
    )


async def _loop(
    scope: SessionScope,
    llm: LLMClient,
    registry: ToolRegistry,
    tenant_id: uuid.UUID,
    conversation_id: uuid.UUID,
    employee_id: uuid.UUID,
    run_id: uuid.UUID,
    system_prompt: str,
    totals: _Totals,
    max_steps: int,
    heartbeat: Heartbeat | None,
) -> tuple[AgentRunStatus, str]:
    for _ in range(max_steps):
        if heartbeat:
            await heartbeat()

        async with scope() as session:
            history = await _history(session, conversation_id)
        messages = [{"role": "system", "content": system_prompt}, *history]

        started = time.perf_counter()
        try:
            response = await llm.complete(messages=messages, tools=registry.schemas())
        except Exception as exc:
            logger.exception("LLM call failed")
            totals.error = f"{type(exc).__name__}: {exc}"[:500]
            async with scope() as session:
                _add_step(
                    session, tenant_id, run_id, totals,
                    kind="llm", name=llm.model, input={"message_count": len(messages)},
                    latency_ms=_ms_since(started), error=totals.error,
                )  # fmt: skip
                session.add(_message(tenant_id, conversation_id, MessageRole.assistant, LLM_FAILED_REPLY))
            return AgentRunStatus.failed, LLM_FAILED_REPLY
        latency_ms = _ms_since(started)

        totals.prompt_tokens += response.usage.prompt_tokens
        totals.completion_tokens += response.usage.completion_tokens
        totals.cost += cost_usd(response.model or llm.model, response.usage)

        async with scope() as session:
            _add_step(
                session, tenant_id, run_id, totals,
                kind="llm",
                name=response.model or llm.model,
                input={"message_count": len(messages)},
                output={
                    "content": response.content,
                    "tool_calls": [{"name": c.name, "arguments": c.arguments} for c in response.tool_calls],
                },
                latency_ms=latency_ms,
                prompt_tokens=response.usage.prompt_tokens,
                completion_tokens=response.usage.completion_tokens,
            )  # fmt: skip
            assistant = _message(tenant_id, conversation_id, MessageRole.assistant, response.content or "")
            assistant.tool_calls = [
                {"id": c.id, "name": c.name, "arguments": c.arguments} for c in response.tool_calls
            ] or None
            session.add(assistant)

            if not response.tool_calls:
                return AgentRunStatus.completed, response.content or ""

            ctx = ToolContext(
                session=session, tenant_id=tenant_id, employee_id=employee_id, conversation_id=conversation_id
            )
            for call in response.tool_calls:
                started = time.perf_counter()
                outcome = await execute_once(ctx, registry, call)
                _add_step(
                    session, tenant_id, run_id, totals,
                    kind="tool", name=call.name,
                    input={"arguments": call.arguments, **({"replayed": True} if outcome.replayed else {})},
                    output=outcome.result, latency_ms=_ms_since(started), error=outcome.error,
                )  # fmt: skip
                tool_message = _message(
                    tenant_id, conversation_id, MessageRole.tool, _dumps(outcome.result)
                )
                tool_message.tool_name = call.name
                tool_message.tool_call_id = call.id
                session.add(tool_message)

    async with scope() as session:
        session.add(_message(tenant_id, conversation_id, MessageRole.assistant, MAX_STEPS_REPLY))
    return AgentRunStatus.max_steps, MAX_STEPS_REPLY


def _message(tenant_id: uuid.UUID, conversation_id: uuid.UUID, role: MessageRole, content: str) -> Message:
    return Message(tenant_id=tenant_id, conversation_id=conversation_id, role=role, content=content)


def _add_step(
    session: AsyncSession, tenant_id: uuid.UUID, run_id: uuid.UUID, totals: _Totals, **fields
) -> None:
    session.add(AgentStep(tenant_id=tenant_id, run_id=run_id, step_index=totals.step_index, **fields))
    totals.step_index += 1


async def _close_run(scope: SessionScope, run_id: uuid.UUID, totals: _Totals, status: AgentRunStatus) -> None:
    async with scope() as session:
        run = await session.get(AgentRun, run_id)
        run.status = status
        run.error = totals.error
        run.prompt_tokens = totals.prompt_tokens
        run.completion_tokens = totals.completion_tokens
        run.cost_usd = totals.cost
        run.finished_at = _utcnow()


def _dumps(value: dict) -> str:
    return json.dumps(value, default=str)


__all__ = ["AgentResult", "SessionScope", "run_agent"]
