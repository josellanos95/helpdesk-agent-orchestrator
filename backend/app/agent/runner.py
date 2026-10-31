"""The agent loop: model -> tool calls -> tool results -> model ... until it answers.

Everything runs inside the caller's tenant-scoped session, so every read and write the
loop or a tool makes is under Row Level Security. Each run leaves a trace (agent_runs /
agent_steps) and the full conversation (messages), including tool calls and results.
"""

import json
import logging
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.prompts import build_system_prompt
from app.agent.tools import ToolContext, ToolRegistry
from app.db.models import AgentRun, AgentRunStatus, AgentStep, Employee, Message, MessageRole, Tenant
from app.llm.base import LLMClient, LLMResponse, ToolCall
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


@dataclass(frozen=True)
class AgentResult:
    run_id: uuid.UUID
    status: AgentRunStatus
    reply: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: Decimal


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)  # columns are timezone-naive UTC


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
    session: AsyncSession,
    llm: LLMClient,
    registry: ToolRegistry,
    tenant_id: uuid.UUID,
    conversation_id: uuid.UUID,
    employee: Employee,
    user_text: str,
    max_steps: int = DEFAULT_MAX_STEPS,
) -> AgentResult:
    tenant = await session.get(Tenant, tenant_id)  # the tenants table is not RLS-scoped
    system_prompt = build_system_prompt(tenant, employee)
    ctx = ToolContext(
        session=session, tenant_id=tenant_id, employee_id=employee.id, conversation_id=conversation_id
    )

    run = AgentRun(tenant_id=tenant_id, conversation_id=conversation_id, model=llm.model)
    session.add(run)
    session.add(
        Message(
            tenant_id=tenant_id, conversation_id=conversation_id, role=MessageRole.user, content=user_text
        )
    )
    await session.flush()

    step_index = 0
    prompt_tokens = completion_tokens = 0
    total_cost = Decimal(0)
    reply: str | None = None
    status = AgentRunStatus.max_steps

    def add_step(**kw) -> None:
        nonlocal step_index
        session.add(AgentStep(tenant_id=tenant_id, run_id=run.id, step_index=step_index, **kw))
        step_index += 1

    for _ in range(max_steps):
        history = await _history(session, conversation_id)
        started = time.perf_counter()
        try:
            response: LLMResponse = await llm.complete(
                messages=[{"role": "system", "content": system_prompt}, *history],
                tools=registry.schemas(),
            )
        except Exception as exc:
            logger.exception("LLM call failed")
            add_step(
                kind="llm",
                name=llm.model,
                input={"message_count": len(history) + 1},
                latency_ms=_ms_since(started),
                error=f"{type(exc).__name__}: {exc}"[:500],
            )
            run.error = f"{type(exc).__name__}: {exc}"[:500]
            status, reply = AgentRunStatus.failed, LLM_FAILED_REPLY
            break

        prompt_tokens += response.usage.prompt_tokens
        completion_tokens += response.usage.completion_tokens
        total_cost += cost_usd(response.model or llm.model, response.usage)
        add_step(
            kind="llm",
            name=response.model or llm.model,
            input={"message_count": len(history) + 1},
            output={
                "content": response.content,
                "tool_calls": [{"name": c.name, "arguments": c.arguments} for c in response.tool_calls],
            },
            latency_ms=_ms_since(started),
            prompt_tokens=response.usage.prompt_tokens,
            completion_tokens=response.usage.completion_tokens,
        )
        session.add(
            Message(
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                role=MessageRole.assistant,
                content=response.content or "",
                tool_calls=[
                    {"id": c.id, "name": c.name, "arguments": c.arguments} for c in response.tool_calls
                ]
                or None,
            )
        )

        if not response.tool_calls:
            status, reply = AgentRunStatus.completed, response.content or ""
            await session.flush()
            break

        for call in response.tool_calls:
            started = time.perf_counter()
            result, error = await _execute_tool(ctx, registry, call)
            add_step(
                kind="tool",
                name=call.name,
                input={"arguments": call.arguments},
                output=result,
                latency_ms=_ms_since(started),
                error=error,
            )
            session.add(
                Message(
                    tenant_id=tenant_id,
                    conversation_id=conversation_id,
                    role=MessageRole.tool,
                    content=json.dumps(result, default=str),
                    tool_name=call.name,
                    tool_call_id=call.id,
                )
            )
        await session.flush()

    if reply is None:
        reply = MAX_STEPS_REPLY
    if status != AgentRunStatus.completed:
        session.add(
            Message(
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                role=MessageRole.assistant,
                content=reply,
            )
        )

    run.status = status
    run.prompt_tokens = prompt_tokens
    run.completion_tokens = completion_tokens
    run.cost_usd = total_cost
    run.finished_at = _utcnow()
    await session.flush()
    return AgentResult(
        run_id=run.id,
        status=status,
        reply=reply,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cost_usd=total_cost,
    )


async def _execute_tool(ctx: ToolContext, registry: ToolRegistry, call: ToolCall) -> tuple[dict, str | None]:
    """Never raises. Failures come back to the model as a tool result so it can recover or explain."""
    tool = registry.get(call.name)
    if tool is None:
        return {"error": f"Unknown tool '{call.name}'."}, "unknown tool"
    try:
        args = tool.args_model.model_validate_json(call.arguments or "{}")
    except ValidationError as exc:
        details = json.loads(exc.json(include_url=False, include_context=False, include_input=False))
        return {"error": "Invalid arguments.", "details": details}, "invalid arguments"
    try:
        # SAVEPOINT: if the tool's SQL fails, only its own work is rolled back and the
        # surrounding transaction (messages, trace) stays usable.
        async with ctx.session.begin_nested():
            return await tool.handler(ctx, args), None
    except Exception as exc:
        logger.exception("Tool %s failed", call.name)
        # The model gets a generic message; internals stay in the trace, not in the prompt.
        return {"error": "The tool failed. Do not retry blindly; tell the user or open a ticket."}, (
            f"{type(exc).__name__}: {exc}"[:500]
        )


def _ms_since(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


__all__ = ["AgentResult", "run_agent"]
