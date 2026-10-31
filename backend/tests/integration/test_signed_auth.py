"""With AUTH_MODE=signed the server, not the caller, decides who is acting and what they may see."""

import uuid

import httpx
import pytest

from app.api.deps import get_embedder, get_llm, get_redis
from app.config import get_settings
from app.db.models import Employee
from app.db.session import AdminSessionLocal
from app.llm.embeddings import HashingEmbedder
from app.main import app
from app.services import demo_token
from tests.fakes import ScriptedLLM, call, say

pytestmark = pytest.mark.integration

SECRET = "t" * 40
RESET = {"reason": "I forgot my password and cannot log in"}


@pytest.fixture(autouse=True)
def signed_mode(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "auth_mode", "signed")
    monkeypatch.setattr(settings, "demo_token_secret", SECRET)
    monkeypatch.setattr(settings, "messages_per_minute_ip", 0)  # many tests share one client address


@pytest.fixture
async def client(redis_client):
    app.dependency_overrides[get_redis] = lambda: redis_client
    app.dependency_overrides[get_embedder] = lambda: HashingEmbedder()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


_tokens: dict[tuple, str] = {}


@pytest.fixture(autouse=True)
def _fresh_tokens():
    _tokens.clear()


def bearer(tenant, employee_id, ttl=3600) -> dict[str, str]:
    """One token per person per test, as a browser would keep: budgets and limits count per session."""
    key = (tenant.id, employee_id, ttl)
    if key not in _tokens:
        _tokens[key], _ = demo_token.issue(
            SECRET, tenant_id=tenant.id, employee_id=employee_id, ttl_seconds=ttl
        )
    return {"Authorization": f"Bearer {_tokens[key]}"}


async def add_employee(tenant, name="Colleague") -> uuid.UUID:
    async with AdminSessionLocal() as session:
        person = Employee(
            tenant_id=tenant.id,
            full_name=name,
            email=f"{uuid.uuid4().hex[:8]}@example.test",
            job_title="Tester",
        )
        session.add(person)
        await session.commit()
        return person.id


async def chat(client, tenant, who, llm, text="hello") -> str:
    """`who` talks to the agent as themselves; returns the conversation id."""
    app.dependency_overrides[get_llm] = lambda: llm
    created = await client.post(
        "/api/conversations", json={"employee_id": str(who)}, headers=bearer(tenant, who)
    )
    assert created.status_code == 201, created.text
    conversation_id = created.json()["id"]
    sent = await client.post(
        f"/api/conversations/{conversation_id}/messages", json={"content": text}, headers=bearer(tenant, who)
    )
    assert sent.status_code == 200, sent.text
    return conversation_id


# ----------------------------------------------------------------------------- who is calling


async def test_no_token_is_a_401_even_with_a_tenant_header(client, two_tenants):
    a = two_tenants.a
    assert (await client.get("/api/employees")).status_code == 401
    assert (await client.get("/api/employees", headers={"X-Tenant-Id": str(a.id)})).status_code == 401


async def test_a_forged_or_expired_token_is_a_401(client, two_tenants):
    a = two_tenants.a
    forged = {"Authorization": "Bearer " + bearer(a, a.employee_id)["Authorization"][7:] + "x"}
    expired = bearer(a, a.employee_id, ttl=-10)
    assert (await client.get("/api/employees", headers=forged)).status_code == 401
    assert (await client.get("/api/employees", headers=expired)).status_code == 401


async def test_the_token_decides_the_tenant_not_the_header(client, two_tenants):
    a, b = two_tenants.a, two_tenants.b
    mine = (await client.get("/api/employees", headers=bearer(a, a.employee_id))).json()
    sneaky = (
        await client.get("/api/employees", headers={**bearer(a, a.employee_id), "X-Tenant-Id": str(b.id)})
    ).json()
    assert [p["id"] for p in mine] == [p["id"] for p in sneaky]
    assert str(a.employee_id) in [p["id"] for p in mine]


async def test_a_token_for_someone_who_no_longer_exists_is_a_401(client, two_tenants):
    a = two_tenants.a
    ghost = bearer(a, uuid.uuid4())
    assert (await client.get("/api/conversations", headers=ghost)).status_code == 401


# ------------------------------------------------------------------------- an ordinary employee


async def test_an_employee_cannot_start_a_conversation_as_someone_else(client, two_tenants):
    a = two_tenants.a
    colleague = await add_employee(a)
    response = await client.post(
        "/api/conversations", json={"employee_id": str(colleague)}, headers=bearer(a, a.employee_id)
    )
    assert response.status_code == 403


async def test_an_employee_cannot_see_a_colleagues_conversation(client, two_tenants):
    a = two_tenants.a
    colleague = await add_employee(a)
    theirs = await chat(client, a, colleague, ScriptedLLM(say("private reply")))
    me = bearer(a, a.employee_id)

    assert (await client.get(f"/api/conversations/{theirs}/messages", headers=me)).status_code == 404
    assert (await client.get(f"/api/conversations/{theirs}/runs", headers=me)).status_code == 404
    sent = await client.post(f"/api/conversations/{theirs}/messages", json={"content": "hi"}, headers=me)
    assert sent.status_code == 404
    listing = (await client.get("/api/conversations", headers=me)).json()
    assert theirs not in [c["id"] for c in listing]
    asking_for_theirs = await client.get(f"/api/conversations?employee_id={colleague}", headers=me)
    assert asking_for_theirs.status_code == 403


async def test_a_run_of_someone_elses_conversation_is_a_404(client, two_tenants):
    a = two_tenants.a
    colleague = await add_employee(a)
    theirs = await chat(client, a, colleague, ScriptedLLM(say("private reply")))
    [run] = (await client.get(f"/api/conversations/{theirs}/runs", headers=bearer(a, colleague))).json()
    assert (await client.get(f"/api/runs/{run['id']}", headers=bearer(a, colleague))).status_code == 200
    assert (await client.get(f"/api/runs/{run['id']}", headers=bearer(a, a.employee_id))).status_code == 404


async def test_an_employee_sees_only_their_own_approvals_and_tickets(client, two_tenants):
    a = two_tenants.a
    colleague = await add_employee(a)
    await chat(client, a, colleague, ScriptedLLM(call("reset_password", RESET), say("pending")), "reset")
    me = bearer(a, a.employee_id)

    assert (await client.get("/api/approvals?status=all", headers=me)).json() == [
        x
        for x in (await client.get("/api/approvals?status=all", headers=me)).json()
        if x["requested_by"] == str(a.employee_id)
    ]
    assert (await client.get(f"/api/approvals?requested_by={colleague}", headers=me)).status_code == 403
    tickets = (await client.get("/api/tickets", headers=me)).json()
    assert tickets and all(t["employee_id"] == str(a.employee_id) for t in tickets)
    assert (await client.get(f"/api/tickets?employee_id={colleague}", headers=me)).status_code == 403


async def test_an_employee_cannot_work_the_human_queue_or_edit_the_knowledge_base(client, two_tenants):
    a = two_tenants.a
    me = bearer(a, a.employee_id)
    assert (await client.get("/api/escalations", headers=me)).status_code == 403
    article = {"title": "Sneaky article", "body": "x" * 40, "author_id": str(a.employee_id)}
    assert (await client.post("/api/kb/articles", json=article, headers=me)).status_code == 403
    assert (await client.get("/api/kb/articles", headers=me)).status_code == 200  # reading is open


# ---------------------------------------------------------------------------- a support agent


async def test_a_support_agent_reads_every_conversation_but_only_talks_in_their_own(
    client, two_tenants, support_agents
):
    a = two_tenants.a
    agent = support_agents["a"]
    theirs = await chat(client, a, a.employee_id, ScriptedLLM(say("hello")))
    boss = bearer(a, agent)

    assert (await client.get(f"/api/conversations/{theirs}/messages", headers=boss)).status_code == 200
    assert theirs in [c["id"] for c in (await client.get("/api/conversations", headers=boss)).json()]
    sent = await client.post(f"/api/conversations/{theirs}/messages", json={"content": "hi"}, headers=boss)
    assert sent.status_code == 404


async def test_the_approver_is_the_caller_whatever_the_body_claims(client, two_tenants, support_agents):
    a = two_tenants.a
    agent = support_agents["a"]
    conversation = await chat(
        client, a, a.employee_id, ScriptedLLM(call("reset_password", RESET), say("pending")), "reset"
    )
    [pending] = (
        await client.get(f"/api/approvals?conversation_id={conversation}", headers=bearer(a, agent))
    ).json()

    # An employee cannot sign, even naming a support agent in the body.
    forged = await client.post(
        f"/api/approvals/{pending['id']}/decision",
        json={"decision": "approve", "approver_id": str(agent)},
        headers=bearer(a, a.employee_id),
    )
    assert forged.status_code == 403
    # The support agent signs; naming the requester in the body changes nothing: the caller is the approver.
    signed = await client.post(
        f"/api/approvals/{pending['id']}/decision",
        json={"decision": "approve", "approver_id": str(a.employee_id)},
        headers=bearer(a, agent),
    )
    assert signed.status_code == 200, signed.text
    decided = (await client.get(f"/api/approvals/{pending['id']}", headers=bearer(a, agent))).json()
    assert decided["decided_by"] == str(agent)


async def test_a_support_agent_cannot_sign_their_own_request(client, two_tenants, support_agents):
    a = two_tenants.a
    agent = support_agents["a"]
    conversation = await chat(
        client, a, agent, ScriptedLLM(call("reset_password", RESET), say("pending")), "reset"
    )
    [pending] = (
        await client.get(f"/api/approvals?conversation_id={conversation}", headers=bearer(a, agent))
    ).json()
    response = await client.post(
        f"/api/approvals/{pending['id']}/decision",
        json={"decision": "approve", "approver_id": str(uuid.uuid4())},
        headers=bearer(a, agent),
    )
    assert response.status_code == 403


async def test_a_support_agent_edits_the_knowledge_base_as_themselves(client, two_tenants, support_agents):
    a = two_tenants.a
    agent = support_agents["a"]
    payload = {
        "title": "Printing basics",
        "body": "To print, choose the office printer. " * 3,
        "author_id": str(uuid.uuid4()),
    }
    created = await client.post("/api/kb/articles", json=payload, headers=bearer(a, agent))
    assert created.status_code == 201, created.text  # the body's author_id was a stranger; the token wins


# --------------------------------------------------------------------------------- other tenants


async def test_a_token_never_reaches_another_tenants_data(client, two_tenants):
    a, b = two_tenants.a, two_tenants.b
    theirs = b.conversation_id
    response = await client.get(f"/api/conversations/{theirs}/messages", headers=bearer(a, a.employee_id))
    assert response.status_code == 404


# ------------------------------------------------------------------------------------ the demo


async def test_the_directory_lists_companies_and_people_without_a_token(client, two_tenants):
    companies = {c["id"]: c for c in (await client.get("/api/demo/directory")).json()}
    mine = companies[str(two_tenants.a.id)]
    assert str(two_tenants.a.employee_id) in [p["id"] for p in mine["people"]]
    assert mine["articles"] == 1


async def test_a_session_can_be_started_for_a_person_of_that_company_only(
    client, two_tenants, support_agents
):
    a, b = two_tenants.a, two_tenants.b
    started = await client.post(
        "/api/demo/session", json={"tenant_id": str(a.id), "employee_id": str(support_agents["a"])}
    )
    assert started.status_code == 200, started.text
    body = started.json()
    assert body["role"] == "support" and body["person"]["id"] == str(support_agents["a"])
    claims = demo_token.verify(SECRET, body["token"])
    assert (claims.tenant_id, claims.employee_id) == (a.id, support_agents["a"])
    # and the token works
    assert (
        await client.get("/api/employees", headers={"Authorization": f"Bearer {body['token']}"})
    ).status_code == 200

    wrong_company = await client.post(
        "/api/demo/session", json={"tenant_id": str(b.id), "employee_id": str(a.employee_id)}
    )
    assert wrong_company.status_code == 404


async def test_minting_sessions_is_rate_limited_per_ip(client, two_tenants, monkeypatch):
    monkeypatch.setattr(get_settings(), "sessions_per_hour_ip", 2)
    a = two_tenants.a
    body = {"tenant_id": str(a.id), "employee_id": str(a.employee_id)}
    assert (await client.post("/api/demo/session", json=body)).status_code == 200
    assert (await client.post("/api/demo/session", json=body)).status_code == 200
    third = await client.post("/api/demo/session", json=body)
    assert third.status_code == 429 and third.json()["detail"]["code"] == "rate_limited"


# --------------------------------------------------------------------------- budget and limits


async def test_a_session_that_spent_its_budget_is_stopped_and_told_why(client, two_tenants, monkeypatch):
    monkeypatch.setattr(get_settings(), "session_budget_usd", 0.00005)  # one scripted reply costs $0.000065
    a = two_tenants.a
    me = bearer(a, a.employee_id)
    conversation = await chat(client, a, a.employee_id, ScriptedLLM(say("first")))

    app.dependency_overrides[get_llm] = lambda: ScriptedLLM(say("second"))
    blocked = await client.post(
        f"/api/conversations/{conversation}/messages", json={"content": "more"}, headers=me
    )
    assert blocked.status_code == 429
    assert blocked.json()["detail"]["code"] == "budget_exhausted_session"

    budget = (await client.get("/api/demo/budget", headers=me)).json()
    assert float(budget["session"]) == 0


async def test_another_session_is_not_blocked_by_this_sessions_budget(client, two_tenants, monkeypatch):
    monkeypatch.setattr(get_settings(), "session_budget_usd", 0.00005)
    a = two_tenants.a
    await chat(client, a, a.employee_id, ScriptedLLM(say("first")))
    colleague = await add_employee(a)
    await chat(client, a, colleague, ScriptedLLM(say("fresh session, fresh budget")))


async def test_messages_are_rate_limited_per_session(client, two_tenants, monkeypatch):
    monkeypatch.setattr(get_settings(), "messages_per_minute_session", 2)
    a = two_tenants.a
    me = bearer(a, a.employee_id)
    conversation = await chat(client, a, a.employee_id, ScriptedLLM(say("one")))
    app.dependency_overrides[get_llm] = lambda: ScriptedLLM(say("two"), say("three"))
    assert (
        await client.post(f"/api/conversations/{conversation}/messages", json={"content": "b"}, headers=me)
    ).status_code == 200
    third = await client.post(
        f"/api/conversations/{conversation}/messages", json={"content": "c"}, headers=me
    )
    assert third.status_code == 429
    assert third.json()["detail"]["code"] == "rate_limited"
    assert "Retry-After" in third.headers


async def test_a_kb_search_is_charged_and_limited(client, two_tenants, support_agents, monkeypatch):
    monkeypatch.setattr(get_settings(), "searches_per_minute_session", 1)
    a = two_tenants.a
    me = bearer(a, a.employee_id)
    first = await client.post("/api/kb/search", json={"query": "fixture passage"}, headers=me)
    assert first.status_code == 200, first.text
    second = await client.post("/api/kb/search", json={"query": "fixture passage"}, headers=me)
    assert second.status_code == 429
