import httpx
import pytest

from app.api.deps import get_llm
from app.config import Settings
from app.main import app
from tests.fakes import ScriptedLLM, call, say

pytestmark = pytest.mark.integration


def headers(tenant) -> dict[str, str]:
    return {"X-Tenant-Id": str(tenant.id)}


@pytest.fixture
async def client():
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
