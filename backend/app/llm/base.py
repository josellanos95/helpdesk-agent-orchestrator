"""Provider-neutral shapes for one chat-completion round trip.

The agent loop only knows these types, so swapping the model or the provider
(M8: any OpenAI-compatible endpoint) never touches the loop.
"""

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: str  # raw JSON exactly as the model produced it; validated by the tool, not here


@dataclass(frozen=True)
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0


@dataclass(frozen=True)
class LLMResponse:
    content: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    model: str = ""


class LLMClient(Protocol):
    model: str

    async def complete(self, *, messages: list[dict], tools: list[dict]) -> LLMResponse: ...
