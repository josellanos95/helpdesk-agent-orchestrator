"""Running one tool call, at most once.

`execute_once` claims the (conversation, tool_call_id) pair in the ledger, runs the tool and stores
the result, all inside the caller's transaction. Consequences:
- a replay of the same call (retried delivery, a resumed run, an approval clicked twice) returns the
  stored result and does not touch the world again
- two concurrent attempts serialise on the unique index: the loser waits, then sees the winner's row
- if the transaction rolls back, the claim rolls back with the tool's effects, so nothing is half-done
"""

import json
import logging
from dataclasses import dataclass

from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.agent.tools import ToolContext, ToolRegistry
from app.db.models import ToolExecution
from app.llm.base import ToolCall

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ToolOutcome:
    result: dict
    error: str | None
    replayed: bool = False


async def execute_once(ctx: ToolContext, registry: ToolRegistry, call: ToolCall) -> ToolOutcome:
    claimed_id = await ctx.session.scalar(
        pg_insert(ToolExecution)
        .values(
            tenant_id=ctx.tenant_id,
            conversation_id=ctx.conversation_id,
            tool_call_id=call.id,
            tool_name=call.name,
            arguments=call.arguments,
        )
        .on_conflict_do_nothing(index_elements=["tenant_id", "conversation_id", "tool_call_id"])
        .returning(ToolExecution.id)
    )
    if claimed_id is None:
        previous = await ctx.session.scalar(
            select(ToolExecution).where(
                ToolExecution.conversation_id == ctx.conversation_id,
                ToolExecution.tool_call_id == call.id,
            )
        )
        return ToolOutcome(result=previous.result or {}, error=previous.error, replayed=True)

    result, error = await run_tool(ctx, registry, call)
    await ctx.session.execute(
        update(ToolExecution).where(ToolExecution.id == claimed_id).values(result=result, error=error)
    )
    return ToolOutcome(result=result, error=error)


async def run_tool(ctx: ToolContext, registry: ToolRegistry, call: ToolCall) -> tuple[dict, str | None]:
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
        # surrounding transaction (messages, trace, the ledger claim) stays usable.
        async with ctx.session.begin_nested():
            return await tool.handler(ctx, args), None
    except Exception as exc:
        logger.exception("Tool %s failed", call.name)
        # The model gets a generic message; internals stay in the trace, not in the prompt.
        return {"error": "The tool failed. Do not retry blindly; tell the user or open a ticket."}, (
            f"{type(exc).__name__}: {exc}"[:500]
        )
