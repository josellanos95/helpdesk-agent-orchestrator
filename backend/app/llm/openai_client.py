import httpx
from openai import NOT_GIVEN, AsyncOpenAI

from app.llm.base import LLMResponse, ToolCall, Usage


class OpenAIClient:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.model = model
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url, http_client=http_client)

    async def complete(self, *, messages: list[dict], tools: list[dict]) -> LLMResponse:
        completion = await self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=tools or NOT_GIVEN,
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
