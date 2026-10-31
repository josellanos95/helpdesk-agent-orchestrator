"""A scripted stand-in for the model, so the agent loop is tested without network or cost."""

import copy
import itertools
import json

from app.llm.base import LLMResponse, ToolCall, Usage

_ids = itertools.count(1)


def say(text: str, *, tokens: tuple[int, int] = (100, 20)) -> LLMResponse:
    return LLMResponse(
        content=text,
        usage=Usage(prompt_tokens=tokens[0], completion_tokens=tokens[1]),
        model="gpt-5-mini",
    )


def call(name: str, arguments: dict | str, *, tokens: tuple[int, int] = (100, 20)) -> LLMResponse:
    raw = arguments if isinstance(arguments, str) else json.dumps(arguments)
    return LLMResponse(
        content=None,
        tool_calls=[ToolCall(id=f"call_{next(_ids)}", name=name, arguments=raw)],
        usage=Usage(prompt_tokens=tokens[0], completion_tokens=tokens[1]),
        model="gpt-5-mini",
    )


class ScriptedLLM:
    """Returns the queued responses in order (an Exception in the queue is raised instead).
    Keeps a deep copy of what it was asked, so tests can assert on the prompts it saw."""

    model = "gpt-5-mini"

    def __init__(self, *responses: LLMResponse | Exception) -> None:
        self._queue = list(responses)
        self.calls: list[dict] = []

    async def complete(self, *, messages: list[dict], tools: list[dict]) -> LLMResponse:
        self.calls.append({"messages": copy.deepcopy(messages), "tools": copy.deepcopy(tools)})
        if not self._queue:
            raise AssertionError("ScriptedLLM was called more times than scripted")
        item = self._queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item
