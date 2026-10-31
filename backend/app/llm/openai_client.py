import httpx
from openai import NOT_GIVEN, AsyncOpenAI

from app.llm.base import LLMResponse, ToolCall, Usage

# The SDK default is a 10-minute timeout, far longer than the 120 s conversation lock. One attempt
# plus one retry at 45 s each stays under it, so a hung call fails the step instead of outliving the lock.
REQUEST_TIMEOUT_SECONDS = 45.0
MAX_RETRIES = 1


class OpenAIClient:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str | None = None,
        http_client: httpx.AsyncClient | None = None,
        timeout: float = REQUEST_TIMEOUT_SECONDS,
        max_retries: int = MAX_RETRIES,
        reasoning_effort: str | None = None,
    ) -> None:
        self.model = model
        self._reasoning_effort = reasoning_effort
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            http_client=http_client,
            timeout=timeout,
            max_retries=max_retries,
        )

    async def complete(self, *, messages: list[dict], tools: list[dict]) -> LLMResponse:
        completion = await self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=tools or NOT_GIVEN,
            reasoning_effort=self._reasoning_effort or NOT_GIVEN,
        )
        message = completion.choices[0].message
        usage = completion.usage
        return LLMResponse(
            content=message.content,
            tool_calls=[
                ToolCall(id=c.id, name=c.function.name, arguments=c.function.arguments)
                for c in (message.tool_calls or [])
                if c.type == "function"
            ],
            usage=Usage(
                prompt_tokens=usage.prompt_tokens if usage else 0,
                completion_tokens=usage.completion_tokens if usage else 0,
            ),
            model=completion.model,
        )
