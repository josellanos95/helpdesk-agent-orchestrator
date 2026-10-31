"""The real OpenAI client against a canned HTTP transport: no network, no cost."""

import json

import httpx

from app.llm.openai_client import OpenAIClient

COMPLETION = {
    "id": "chatcmpl-1",
    "object": "chat.completion",
    "created": 1,
    "model": "gpt-5-mini-2025-08-07",
    "choices": [
        {
            "index": 0,
            "finish_reason": "tool_calls",
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_abc",
                        "type": "function",
                        "function": {"name": "check_system_status", "arguments": '{"system_name": "VPN"}'},
                    }
                ],
            },
        }
    ],
    "usage": {"prompt_tokens": 321, "completion_tokens": 45, "total_tokens": 366},
}


def make_client(captured: list[dict], payload: dict = COMPLETION) -> OpenAIClient:
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(
            {
                "path": request.url.path,
                "auth": request.headers["authorization"],
                "body": json.loads(request.content),
            }
        )
        return httpx.Response(200, json=payload)

    return OpenAIClient(
        api_key="sk-test",
        model="gpt-5-mini",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


async def test_sends_model_messages_and_tools_and_parses_tool_calls_and_usage():
    captured: list[dict] = []
    function = {"name": "check_system_status", "parameters": {"type": "object"}}
    tools = [{"type": "function", "function": function}]
    response = await make_client(captured).complete(
        messages=[{"role": "user", "content": "is the VPN up?"}], tools=tools
    )

    [request] = captured
    assert request["path"].endswith("/chat/completions")
    assert request["auth"] == "Bearer sk-test"
    assert request["body"]["model"] == "gpt-5-mini"
    assert request["body"]["tools"] == tools
    # gpt-5 models reject custom sampling parameters; we must not send any.
    assert not ({"temperature", "max_tokens", "top_p"} & set(request["body"]))

    assert response.content is None
    [tool_call] = response.tool_calls
    assert (tool_call.id, tool_call.name, tool_call.arguments) == (
        "call_abc",
        "check_system_status",
        '{"system_name": "VPN"}',
    )
    assert (response.usage.prompt_tokens, response.usage.completion_tokens) == (321, 45)
    assert response.model == "gpt-5-mini-2025-08-07"


async def test_omits_the_tools_field_when_there_are_no_tools():
    captured: list[dict] = []
    text_only = {
        **COMPLETION,
        "choices": [
            {"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "Hi!"}}
        ],
    }
    client = make_client(captured, text_only)
    response = await client.complete(messages=[{"role": "user", "content": "hi"}], tools=[])

    assert "tools" not in captured[0]["body"]
    assert response.content == "Hi!" and response.tool_calls == []


def test_each_call_is_bounded_well_below_the_conversation_lock_ttl():
    """A hung provider call must fail the step before the 120 s lock could expire under it."""
    from app.config import Settings
    from app.llm.openai_client import MAX_RETRIES, REQUEST_TIMEOUT_SECONDS

    client = OpenAIClient(api_key="sk-test", model="gpt-5-mini")
    assert client._client.timeout == REQUEST_TIMEOUT_SECONDS
    assert client._client.max_retries == MAX_RETRIES
    worst_case = REQUEST_TIMEOUT_SECONDS * (MAX_RETRIES + 1)
    assert worst_case < Settings(_env_file=None).conversation_lock_ttl_seconds


async def test_reasoning_effort_is_sent_only_when_asked_for():
    default, low = [], []
    await make_client(default).complete(messages=[{"role": "user", "content": "hi"}], tools=[])
    client = OpenAIClient(
        api_key="sk-test",
        model="gpt-5-mini",
        reasoning_effort="low",
        http_client=httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: (
                    low.append(json.loads(request.content)),
                    httpx.Response(200, json=COMPLETION),
                )[1]
            )
        ),
    )
    await client.complete(messages=[{"role": "user", "content": "hi"}], tools=[])

    assert "reasoning_effort" not in default[0]["body"]
    assert low[0]["reasoning_effort"] == "low"
