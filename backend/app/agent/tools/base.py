import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.embeddings import Embedder


@dataclass(frozen=True)
class ToolContext:
    """Who the tool is acting for. Taken from the authenticated request, never from the model:
    no tool takes a tenant, employee or conversation id as an argument."""

    session: AsyncSession  # tenant-scoped (RLS-enforced)
    tenant_id: uuid.UUID
    employee_id: uuid.UUID
    conversation_id: uuid.UUID
    # Turns text into vectors for knowledge-base search; None when embeddings are not configured.
    embedder: Embedder | None = None
    # Adds a cost that is not a model call (an embedding) to the run's total, so caps see it.
    charge: Callable[[Decimal], None] = lambda usd: None


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    args_model: type[BaseModel]
    handler: Callable[[ToolContext, Any], Awaitable[dict]]
    # Sensitive actions will pause for a human in M5; declared now so tools state it up front.
    requires_approval: bool = False

    def openai_schema(self) -> dict:
        schema = self.args_model.model_json_schema()
        schema.pop("title", None)
        return {
            "type": "function",
            "function": {"name": self.name, "description": self.description, "parameters": schema},
        }


class ToolRegistry:
    def __init__(self, tools: list[Tool]) -> None:
        self._tools = {t.name: t for t in tools}

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def schemas(self) -> list[dict]:
        return [t.openai_schema() for t in self._tools.values()]
