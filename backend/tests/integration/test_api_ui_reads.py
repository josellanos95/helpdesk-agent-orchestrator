"""The read endpoints the web app is built on: conversation list, live runs, message-to-step links."""

import uuid

import httpx
import pytest

from app.api.deps import get_embedder, get_llm, get_redis
from app.llm.embeddings import HashingEmbedder
from app.main import app
from tests.fakes import ScriptedLLM, call, say

pytestmark = pytest.mark.integration

RESET = {"reason": "I forgot my password and cannot log in"}


def headers(tenant) -> dict[str, str]:
    return {"X-Tenant-Id": str(tenant.id)}


@pytest.fixture
async def client(redis_client):
    app.dependency_overrides[get_redis] = lambda: redis_client
    app.dependency_overrides[get_embedder] = lambda: HashingEmbedder()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


async def chat(client, tenant, llm, text="hello", employee_id=None, conversation_id=None) -> str:
    app.dependency_overrides[get_llm] = lambda: llm
    if conversation_id is None:
        created = await client.post(
            "/api/conversations",
            json={"employee_id": str(employee_id or tenant.employee_id)},
            headers=headers(tenant),
        )
        conversation_id = created.json()["id"]
    sent = await client.post(
        f"/api/conversations/{conversation_id}/messages", json={"content": text}, headers=headers(tenant)
    )
    assert sent.status_code == 200, sent.text
    return conversation_id


async def test_each_message_points_at_the_run_and_step_that_produced_it(client, two_tenants):
    a = two_tenants.a
    llm = ScriptedLLM(call("list_my_tickets", {}), say("You have none."))
    conversation_id = await chat(client, a, llm, "what tickets do I have?")

    messages = (await client.get(f"/api/conversations/{conversation_id}/messages", headers=headers(a))).json()
    runs = (await client.get(f"/api/conversations/{conversation_id}/runs", headers=headers(a))).json()
    [run] = runs
    steps = {s["step_index"]: s for s in run["steps"]}

    assert [m["role"] for m in messages] == ["user", "assistant", "tool", "assistant"]
    assert {m["run_id"] for m in messages} == {run["id"]}
    assert messages[0]["step_index"] is None  # the user's own line has no step
    assert steps[messages[1]["step_index"]]["kind"] == "llm"
    assert steps[messages[2]["step_index"]]["kind"] == "tool"
    assert steps[messages[2]["step_index"]]["name"] == messages[2]["tool_name"] == "list_my_tickets"
    assert steps[messages[3]["step_index"]]["kind"] == "llm"
    assert [m["seq"] for m in messages] == sorted(m["seq"] for m in messages)


async def test_a_failed_model_call_still_links_its_apology_to_the_failing_step(client, two_tenants):
    a = two_tenants.a
    conversation_id = await chat(client, a, ScriptedLLM(RuntimeError("provider down")))
    messages = (await client.get(f"/api/conversations/{conversation_id}/messages", headers=headers(a))).json()
    [run] = (await client.get(f"/api/conversations/{conversation_id}/runs", headers=headers(a))).json()

    assert run["status"] == "failed"
    failing = next(s for s in run["steps"] if s["error"])
    assert messages[-1]["step_index"] == failing["step_index"]


async def test_the_runs_of_a_conversation_come_in_order_with_their_steps(client, two_tenants):
    a = two_tenants.a
    conversation_id = await chat(client, a, ScriptedLLM(say("first")), "one")
    await chat(
        client,
        a,
        ScriptedLLM(call("list_my_tickets", {}), say("second")),
        "two",
        conversation_id=conversation_id,
    )

    runs = (await client.get(f"/api/conversations/{conversation_id}/runs", headers=headers(a))).json()
    assert [r["status"] for r in runs] == ["completed", "completed"]
    assert [len(r["steps"]) for r in runs] == [1, 3]
    assert runs[0]["started_at"] <= runs[1]["started_at"]


async def test_runs_of_another_tenants_conversation_are_a_404(client, two_tenants):
    conversation_id = await chat(client, two_tenants.a, ScriptedLLM(say("hi")))
    response = await client.get(f"/api/conversations/{conversation_id}/runs", headers=headers(two_tenants.b))
    assert response.status_code == 404


async def test_the_conversation_list_has_preview_owner_and_pending_approvals(client, two_tenants):
    a = two_tenants.a
    conversation_id = await chat(
        client, a, ScriptedLLM(call("reset_password", RESET), say("It is waiting for approval.")), "reset me"
    )

    listing = (await client.get("/api/conversations", headers=headers(a))).json()
    [mine] = [c for c in listing if c["id"] == conversation_id]
    assert mine["employee_name"] == "Emp a"
    assert mine["preview"] == "It is waiting for approval."
    assert mine["title"] == "reset me"  # what the employee first asked, not the agent's last words
    assert mine["pending_approvals"] == 1


async def test_the_list_is_newest_activity_first_and_can_be_filtered_to_one_employee(
    client, two_tenants, support_agents
):
    a = two_tenants.a
    older = await chat(client, a, ScriptedLLM(say("older")), "old question")
    other = await chat(client, a, ScriptedLLM(say("theirs")), "mine", employee_id=support_agents["a"])
    newer = await chat(client, a, ScriptedLLM(say("newer")), "new question")
    # activity in the old conversation moves it to the top
    await chat(client, a, ScriptedLLM(say("back again")), "more", conversation_id=older)

    everything = [c["id"] for c in (await client.get("/api/conversations", headers=headers(a))).json()]
    assert everything.index(older) < everything.index(newer) < everything.index(other)

    only_support_agent = (
        await client.get(f"/api/conversations?employee_id={support_agents['a']}", headers=headers(a))
    ).json()
    assert [c["id"] for c in only_support_agent] == [other]


async def test_an_empty_conversation_is_listed_without_a_preview(client, two_tenants):
    a = two_tenants.a
    created = await client.post(
        "/api/conversations", json={"employee_id": str(a.employee_id)}, headers=headers(a)
    )
    [mine] = [
        c
        for c in (await client.get("/api/conversations", headers=headers(a))).json()
        if c["id"] == created.json()["id"]
    ]
    assert mine["preview"] == "" and mine["title"] == "" and mine["pending_approvals"] == 0


async def test_a_tenant_only_lists_its_own_conversations(client, two_tenants):
    theirs = await chat(client, two_tenants.b, ScriptedLLM(say("b")))
    listing = (await client.get("/api/conversations", headers=headers(two_tenants.a))).json()
    assert theirs not in [c["id"] for c in listing]


async def test_approvals_can_be_filtered_by_conversation_and_requester(client, two_tenants):
    a = two_tenants.a
    first = await chat(client, a, ScriptedLLM(call("reset_password", RESET), say("pending")), "reset")
    second = await chat(
        client,
        a,
        ScriptedLLM(call("reset_password", {"reason": "locked out of the vpn too"}), say("pending")),
        "reset again",
    )

    only_first = (
        await client.get(f"/api/approvals?status=all&conversation_id={first}", headers=headers(a))
    ).json()
    mine = (
        await client.get(f"/api/approvals?status=all&requested_by={a.employee_id}", headers=headers(a))
    ).json()
    nobody = (
        await client.get(f"/api/approvals?status=all&requested_by={uuid.uuid4()}", headers=headers(a))
    ).json()

    assert [x["conversation_id"] for x in only_first] == [first]
    assert {first, second} <= {x["conversation_id"] for x in mine}
    assert nobody == []


async def test_tickets_list_newest_first_and_filter_by_employee(client, two_tenants, support_agents):
    a = two_tenants.a
    everything = (await client.get("/api/tickets", headers=headers(a))).json()
    assert everything
    assert {"subject", "status", "priority", "category", "employee_name"} <= everything[0].keys()
    stamps = [t["created_at"] for t in everything]
    assert stamps == sorted(stamps, reverse=True)

    nobody = (await client.get(f"/api/tickets?employee_id={uuid.uuid4()}", headers=headers(a))).json()
    assert nobody == []


async def test_a_tenant_only_lists_its_own_tickets(client, two_tenants):
    theirs = {t["id"] for t in (await client.get("/api/tickets", headers=headers(two_tenants.b))).json()}
    mine = {t["id"] for t in (await client.get("/api/tickets", headers=headers(two_tenants.a))).json()}
    assert theirs and mine and not theirs & mine
