import asyncio
import uuid

import httpx
import pytest
import redis.asyncio as redis
from sqlalchemy import func, select

import app.api.routes.conversations as conversations_module
from app.api.deps import get_llm, get_redis
from app.config import Settings
from app.db.models import Ticket
from app.db.session import AdminSessionLocal
from app.main import app
from tests.fakes import GatedLLM, ScriptedLLM, call, say

pytestmark = pytest.mark.integration


def headers(tenant) -> dict[str, str]:
    return {"X-Tenant-Id": str(tenant.id)}


@pytest.fixture
async def client(redis_client):
    app.dependency_overrides[get_redis] = lambda: redis_client
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


def use_llm(llm: ScriptedLLM) -> ScriptedLLM:
    app.dependency_overrides[get_llm] = lambda: llm
    return llm


async def open_conversation(client, tenant) -> str:
    response = await client.post(
        "/api/conversations", json={"employee_id": str(tenant.employee_id)}, headers=headers(tenant)
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def test_full_flow_chat_with_a_tool_call_then_read_the_trace(client, two_tenants):
    use_llm(
        ScriptedLLM(
            call(
                "create_ticket",
                {
                    "category": "network",
                    "subject": "VPN keeps dropping",
                    "description": "Drops every 10 minutes.",
                },
            ),
            say("I opened a ticket for you."),
        )
    )
    a = two_tenants.a
    conversation_id = await open_conversation(client, a)

    reply = await client.post(
        f"/api/conversations/{conversation_id}/messages",
        json={"content": "my VPN keeps dropping"},
        headers=headers(a),
    )
    assert reply.status_code == 200, reply.text
    body = reply.json()
    assert body["reply"] == "I opened a ticket for you."
    assert body["run"]["status"] == "completed"
    assert body["run"]["prompt_tokens"] == 200

    # The change was committed: a *new* request sees the conversation.
    history = await client.get(f"/api/conversations/{conversation_id}/messages", headers=headers(a))
    assert [m["role"] for m in history.json()] == ["user", "assistant", "tool", "assistant"]
    assert history.json()[1]["tool_calls"][0]["name"] == "create_ticket"

    run = await client.get(f"/api/runs/{body['run']['run_id']}", headers=headers(a))
    assert run.status_code == 200
    assert [(s["kind"], s["name"]) for s in run.json()["steps"]] == [
        ("llm", "gpt-5-mini"),
        ("tool", "create_ticket"),
        ("llm", "gpt-5-mini"),
    ]


async def test_employees_are_listed_per_tenant(client, two_tenants):
    response = await client.get("/api/employees", headers=headers(two_tenants.a))
    assert [e["full_name"] for e in response.json()] == ["Emp a"]


async def test_other_tenants_cannot_read_or_write_a_conversation(client, two_tenants):
    use_llm(ScriptedLLM(say("should never be called")))
    conversation_id = await open_conversation(client, two_tenants.a)
    intruder = headers(two_tenants.b)

    read = await client.get(f"/api/conversations/{conversation_id}/messages", headers=intruder)
    write = await client.post(
        f"/api/conversations/{conversation_id}/messages", json={"content": "hello?"}, headers=intruder
    )
    assert read.status_code == 404
    assert write.status_code == 404


async def test_other_tenants_cannot_read_a_run(client, two_tenants):
    use_llm(ScriptedLLM(say("hi")))
    conversation_id = await open_conversation(client, two_tenants.a)
    a = headers(two_tenants.a)
    reply = await client.post(
        f"/api/conversations/{conversation_id}/messages", json={"content": "hi"}, headers=a
    )
    run_id = reply.json()["run"]["run_id"]

    assert (await client.get(f"/api/runs/{run_id}", headers=headers(two_tenants.a))).status_code == 200
    assert (await client.get(f"/api/runs/{run_id}", headers=headers(two_tenants.b))).status_code == 404


async def test_cannot_start_a_conversation_as_another_tenants_employee(client, two_tenants):
    response = await client.post(
        "/api/conversations",
        json={"employee_id": str(two_tenants.b.employee_id)},
        headers=headers(two_tenants.a),
    )
    assert response.status_code == 404


@pytest.mark.parametrize("content", ["", "x" * 4001])
async def test_message_length_is_validated(client, two_tenants, content):
    use_llm(ScriptedLLM(say("unused")))
    conversation_id = await open_conversation(client, two_tenants.a)
    response = await client.post(
        f"/api/conversations/{conversation_id}/messages",
        json={"content": content},
        headers=headers(two_tenants.a),
    )
    assert response.status_code == 422


async def test_llm_outage_still_returns_a_reply_and_records_the_failed_run(client, two_tenants):
    use_llm(ScriptedLLM(RuntimeError("provider down")))
    a = two_tenants.a
    conversation_id = await open_conversation(client, a)
    response = await client.post(
        f"/api/conversations/{conversation_id}/messages", json={"content": "hi"}, headers=headers(a)
    )
    assert response.status_code == 200
    assert response.json()["run"]["status"] == "failed"
    run = await client.get(f"/api/runs/{response.json()['run']['run_id']}", headers=headers(a))
    assert "provider down" in run.json()["error"]


async def test_missing_api_key_is_a_clear_503(client, two_tenants, monkeypatch):
    monkeypatch.setattr("app.api.deps.get_settings", lambda: Settings(openai_api_key=None, _env_file=None))
    conversation_id = await open_conversation(client, two_tenants.a)
    response = await client.post(
        f"/api/conversations/{conversation_id}/messages",
        json={"content": "hi"},
        headers=headers(two_tenants.a),
    )
    assert response.status_code == 503
    assert "OPENAI_API_KEY" in response.json()["detail"]


# --- M4: one run per conversation, and idempotent retries ------------------------------------


def post_message(client, conversation_id, content, tenant, **extra_headers):
    return client.post(
        f"/api/conversations/{conversation_id}/messages",
        json={"content": content},
        headers={**headers(tenant), **extra_headers},
    )


async def tickets_in(conversation_id: str) -> int:
    async with AdminSessionLocal() as session:
        return await session.scalar(
            select(func.count())
            .select_from(Ticket)
            .where(Ticket.conversation_id == uuid.UUID(conversation_id))
        )


TICKET_CALL = (
    "create_ticket",
    {
        "category": "network",
        "subject": "VPN keeps dropping",
        "description": "Drops every 10 minutes since Monday.",
    },
)


async def test_a_second_message_on_a_busy_conversation_gets_409_and_is_never_stored(client, two_tenants):
    a = two_tenants.a
    llm = use_llm(GatedLLM(say("first answer"), say("third answer")))
    conversation_id = await open_conversation(client, a)

    first = asyncio.create_task(post_message(client, conversation_id, "one", a))
    await asyncio.wait_for(llm.entered.wait(), 5)

    try:
        # Bounded: if the lock ever stops excluding, this request would wait on the gate forever.
        busy = await asyncio.wait_for(post_message(client, conversation_id, "two", a), 5)
    finally:
        llm.gate.set()
    assert busy.status_code == 409
    assert "already being processed" in busy.json()["detail"]

    assert (await first).status_code == 200
    assert (await post_message(client, conversation_id, "three", a)).status_code == 200  # lock released

    history = await client.get(f"/api/conversations/{conversation_id}/messages", headers=headers(a))
    assert [(m["role"], m["content"]) for m in history.json()] == [
        ("user", "one"),
        ("assistant", "first answer"),
        ("user", "three"),
        ("assistant", "third answer"),
    ]


async def test_different_conversations_run_in_parallel(client, two_tenants):
    a = two_tenants.a
    llm = use_llm(GatedLLM(say("x"), say("y")))
    first_id = await open_conversation(client, a)
    second_id = await open_conversation(client, a)

    first = asyncio.create_task(post_message(client, first_id, "hi", a))
    second = asyncio.create_task(post_message(client, second_id, "hi", a))
    await asyncio.sleep(0.3)
    llm.gate.set()
    assert [r.status_code for r in await asyncio.gather(first, second)] == [200, 200]


async def test_retrying_with_the_same_idempotency_key_replays_without_running_again(client, two_tenants):
    a = two_tenants.a
    llm = use_llm(ScriptedLLM(call(*TICKET_CALL), say("I opened a ticket.")))
    conversation_id = await open_conversation(client, a)

    first = await post_message(client, conversation_id, "my VPN drops", a, **{"Idempotency-Key": "k-1"})
    retry = await post_message(client, conversation_id, "my VPN drops", a, **{"Idempotency-Key": "k-1"})

    assert first.status_code == retry.status_code == 200
    assert retry.json() == first.json()
    assert retry.headers["idempotent-replay"] == "true"
    assert "idempotent-replay" not in first.headers
    assert len(llm.calls) == 2  # the model ran for the first request only
    assert await tickets_in(conversation_id) == 1


async def test_the_same_key_with_a_different_request_is_rejected(client, two_tenants):
    a = two_tenants.a
    use_llm(ScriptedLLM(say("ok")))
    conversation_id = await open_conversation(client, a)
    other_id = await open_conversation(client, a)
    await post_message(client, conversation_id, "hello", a, **{"Idempotency-Key": "k-2"})

    different_body = await post_message(client, conversation_id, "goodbye", a, **{"Idempotency-Key": "k-2"})
    different_conversation = await post_message(client, other_id, "hello", a, **{"Idempotency-Key": "k-2"})

    assert different_body.status_code == different_conversation.status_code == 422


async def test_the_same_key_while_the_first_request_is_still_running_gets_409(client, two_tenants):
    a = two_tenants.a
    llm = use_llm(GatedLLM(say("done")))
    conversation_id = await open_conversation(client, a)

    first = asyncio.create_task(
        post_message(client, conversation_id, "hello", a, **{"Idempotency-Key": "k-3"})
    )
    await asyncio.wait_for(llm.entered.wait(), 5)
    second = await post_message(client, conversation_id, "hello", a, **{"Idempotency-Key": "k-3"})
    llm.gate.set()

    assert second.status_code == 409 and "Idempotency-Key" in second.json()["detail"]
    assert (await first).status_code == 200


async def test_keys_are_scoped_per_tenant(client, two_tenants):
    use_llm(ScriptedLLM(say("a"), say("b")))
    conversation_a = await open_conversation(client, two_tenants.a)
    conversation_b = await open_conversation(client, two_tenants.b)

    ra = await post_message(client, conversation_a, "hi", two_tenants.a, **{"Idempotency-Key": "shared"})
    rb = await post_message(client, conversation_b, "hi", two_tenants.b, **{"Idempotency-Key": "shared"})

    assert ra.status_code == rb.status_code == 200
    assert "idempotent-replay" not in rb.headers
    assert ra.json()["reply"] == "a" and rb.json()["reply"] == "b"


async def test_a_provider_outage_releases_the_key_so_the_retry_really_runs(client, two_tenants):
    a = two_tenants.a
    conversation_id = await open_conversation(client, a)
    use_llm(ScriptedLLM(RuntimeError("provider down")))
    failed = await post_message(client, conversation_id, "hello", a, **{"Idempotency-Key": "k-4"})
    assert failed.json()["run"]["status"] == "failed"

    use_llm(ScriptedLLM(say("back online")))
    retry = await post_message(client, conversation_id, "hello", a, **{"Idempotency-Key": "k-4"})
    assert retry.json()["reply"] == "back online"
    assert "idempotent-replay" not in retry.headers


async def test_an_unexpected_server_error_releases_the_key_and_the_lock(client, two_tenants, monkeypatch):
    a = two_tenants.a
    use_llm(ScriptedLLM(say("fine")))
    conversation_id = await open_conversation(client, a)

    async def broken(**kwargs):
        raise RuntimeError("bug")

    real = conversations_module.run_agent
    monkeypatch.setattr(conversations_module, "run_agent", broken)
    with pytest.raises(RuntimeError, match="bug"):
        await post_message(client, conversation_id, "hello", a, **{"Idempotency-Key": "k-5"})

    monkeypatch.setattr(conversations_module, "run_agent", real)
    retry = await post_message(client, conversation_id, "hello", a, **{"Idempotency-Key": "k-5"})
    assert retry.status_code == 200 and "idempotent-replay" not in retry.headers


async def test_redis_being_down_is_a_503_and_leaves_the_key_usable(client, two_tenants, redis_client):
    a = two_tenants.a
    use_llm(ScriptedLLM(say("fine")))
    conversation_id = await open_conversation(client, a)

    dead = redis.Redis.from_url("redis://localhost:6399/0", decode_responses=True)
    app.dependency_overrides[get_redis] = lambda: dead
    down = await post_message(client, conversation_id, "hello", a, **{"Idempotency-Key": "k-6"})
    await dead.aclose()
    assert down.status_code == 503

    app.dependency_overrides[get_redis] = lambda: redis_client
    retry = await post_message(client, conversation_id, "hello", a, **{"Idempotency-Key": "k-6"})
    assert retry.status_code == 200


@pytest.mark.parametrize("key", ["", "k" * 201])
async def test_idempotency_key_length_is_validated(client, two_tenants, key):
    use_llm(ScriptedLLM(say("unused")))
    conversation_id = await open_conversation(client, two_tenants.a)
    response = await post_message(client, conversation_id, "hi", two_tenants.a, **{"Idempotency-Key": key})
    assert response.status_code == 422
