import uuid

import httpx
import pytest

from app.api.deps import get_embedder, get_llm, get_redis
from app.llm.embeddings import HashingEmbedder
from app.main import app
from tests.fakes import ScriptedLLM, call, say

pytestmark = pytest.mark.integration

VPN = {
    "title": "VPN troubleshooting",
    "body": (
        "If the VPN client disconnects every few minutes, update the client to version 5 and sign in again."
    ),
}


class CountingEmbedder(HashingEmbedder):
    def __init__(self) -> None:
        super().__init__()
        self.texts_embedded = 0

    async def embed(self, texts):
        self.texts_embedded += len(texts)
        return await super().embed(texts)


def headers(tenant) -> dict[str, str]:
    return {"X-Tenant-Id": str(tenant.id)}


@pytest.fixture
def embedder() -> CountingEmbedder:
    return CountingEmbedder()


@pytest.fixture
async def client(redis_client, embedder):
    app.dependency_overrides[get_redis] = lambda: redis_client
    app.dependency_overrides[get_embedder] = lambda: embedder
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


def create(client, tenant, author, article=VPN):
    return client.post(
        "/api/kb/articles", json={**article, "author_id": str(author)}, headers=headers(tenant)
    )


async def test_a_support_agent_writes_an_article_and_it_can_be_listed_read_and_searched(
    client, two_tenants, support_agents
):
    a = two_tenants.a
    created = await create(client, a, support_agents["a"])
    assert created.status_code == 201 and created.json()["passages"] >= 1
    article_id = created.json()["id"]

    listing = (await client.get("/api/kb/articles", headers=headers(a))).json()
    assert "VPN troubleshooting" in [x["title"] for x in listing]
    assert all(x["body"] is None for x in listing)  # the listing stays light

    shown = (await client.get(f"/api/kb/articles/{article_id}", headers=headers(a))).json()
    assert shown["body"] == VPN["body"]

    found = await client.post(
        "/api/kb/search", json={"query": "VPN client disconnects every few minutes"}, headers=headers(a)
    )
    assert found.status_code == 200
    assert found.json()[0]["article"] == "VPN troubleshooting"
    assert found.json()[0]["keyword_match"] is True and found.json()[0]["similarity"] > 0.3


async def test_only_support_agents_of_the_tenant_can_write(client, two_tenants, support_agents):
    a = two_tenants.a
    ordinary = await create(client, a, a.employee_id)
    unknown = await create(client, a, uuid.uuid4())
    other_tenants_agent = await create(client, a, support_agents["b"])
    assert ordinary.status_code == unknown.status_code == other_tenants_agent.status_code == 403

    listing = (await client.get("/api/kb/articles", headers=headers(a))).json()
    assert "VPN troubleshooting" not in [x["title"] for x in listing]


async def test_a_duplicate_title_is_a_409_and_bad_input_a_422(client, two_tenants, support_agents):
    a, agent = two_tenants.a, support_agents["a"]
    await create(client, a, agent)
    assert (await create(client, a, agent)).status_code == 409
    assert (await create(client, a, agent, {"title": "ab", "body": VPN["body"]})).status_code == 422
    assert (await create(client, a, agent, {"title": "Fine title", "body": "too short"})).status_code == 422
    assert (await create(client, a, agent, {"title": "Huge", "body": "x" * 20_001})).status_code == 422


async def test_updating_with_identical_content_does_not_pay_for_new_embeddings(
    client, two_tenants, support_agents, embedder
):
    a, agent = two_tenants.a, support_agents["a"]
    article_id = (await create(client, a, agent)).json()["id"]
    paid_for_creation = embedder.texts_embedded

    same = await client.put(
        f"/api/kb/articles/{article_id}", json={**VPN, "author_id": str(agent)}, headers=headers(a)
    )
    assert same.status_code == 200 and same.json()["changed"] is False
    assert embedder.texts_embedded == paid_for_creation  # not a single extra embedding was requested

    edited = await client.put(
        f"/api/kb/articles/{article_id}",
        json={"title": VPN["title"], "body": "Use the new client. " * 5, "author_id": str(agent)},
        headers=headers(a),
    )
    assert edited.json()["changed"] is True and embedder.texts_embedded > paid_for_creation


async def test_renaming_alone_is_a_change_and_is_re_embedded(client, two_tenants, support_agents, embedder):
    a, agent = two_tenants.a, support_agents["a"]
    article_id = (await create(client, a, agent)).json()["id"]
    paid = embedder.texts_embedded

    renamed = await client.put(
        f"/api/kb/articles/{article_id}",
        json={"title": "VPN: dropping connections", "body": VPN["body"], "author_id": str(agent)},
        headers=headers(a),
    )
    assert (
        renamed.json()["changed"] is True and embedder.texts_embedded > paid
    )  # the title is part of each passage


async def test_deleting_removes_the_article_from_search(client, two_tenants, support_agents):
    a, agent = two_tenants.a, support_agents["a"]
    article_id = (await create(client, a, agent)).json()["id"]
    query = {"query": "VPN client disconnects every few minutes"}

    assert (
        await client.delete(f"/api/kb/articles/{article_id}?actor_id={agent}", headers=headers(a))
    ).status_code == 204
    assert (await client.post("/api/kb/search", json=query, headers=headers(a))).json() == []
    assert (
        await client.delete(f"/api/kb/articles/{article_id}?actor_id={agent}", headers=headers(a))
    ).status_code == 404


async def test_deleting_needs_a_support_agent(client, two_tenants, support_agents):
    a = two_tenants.a
    article_id = (await create(client, a, support_agents["a"])).json()["id"]
    refused = await client.delete(
        f"/api/kb/articles/{article_id}?actor_id={a.employee_id}", headers=headers(a)
    )
    assert refused.status_code == 403
    assert (await client.get(f"/api/kb/articles/{article_id}", headers=headers(a))).status_code == 200


async def test_one_tenant_cannot_read_search_edit_or_delete_anothers_articles(
    client, two_tenants, support_agents
):
    a, b = two_tenants.a, two_tenants.b
    article_id = (await create(client, a, support_agents["a"])).json()["id"]

    assert (await client.get(f"/api/kb/articles/{article_id}", headers=headers(b))).status_code == 404
    listing_b = (await client.get("/api/kb/articles", headers=headers(b))).json()
    assert "VPN troubleshooting" not in [x["title"] for x in listing_b]
    assert (
        await client.post("/api/kb/search", json={"query": "VPN client disconnects"}, headers=headers(b))
    ).json() == []
    assert (
        await client.put(
            f"/api/kb/articles/{article_id}",
            json={**VPN, "author_id": str(support_agents["b"])},
            headers=headers(b),
        )
    ).status_code == 404
    assert (
        await client.delete(
            f"/api/kb/articles/{article_id}?actor_id={support_agents['b']}", headers=headers(b)
        )
    ).status_code == 404


@pytest.mark.parametrize(
    "payload", [{"query": "hi"}, {"query": "valid query", "top_k": 0}, {"query": "valid query", "top_k": 9}]
)
async def test_search_input_is_validated(client, two_tenants, payload):
    assert (
        await client.post("/api/kb/search", json=payload, headers=headers(two_tenants.a))
    ).status_code == 422


async def test_without_an_embedding_provider_the_kb_says_503(two_tenants, support_agents, redis_client):
    app.dependency_overrides[get_redis] = lambda: redis_client
    app.dependency_overrides[get_embedder] = lambda: None
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            created = await create(c, two_tenants.a, support_agents["a"])
            searched = await c.post(
                "/api/kb/search", json={"query": "anything at all"}, headers=headers(two_tenants.a)
            )
    finally:
        app.dependency_overrides.clear()
    assert created.status_code == searched.status_code == 503


async def test_the_agent_answers_from_the_kb_through_the_whole_stack(client, two_tenants, support_agents):
    a = two_tenants.a
    await create(client, a, support_agents["a"])
    llm = ScriptedLLM(
        call("search_knowledge_base", {"query": "VPN client disconnects every few minutes"}),
        say('According to "VPN troubleshooting", update the client to version 5.'),
    )
    app.dependency_overrides[get_llm] = lambda: llm

    conversation_id = (
        await client.post("/api/conversations", json={"employee_id": str(a.employee_id)}, headers=headers(a))
    ).json()["id"]
    reply = await client.post(
        f"/api/conversations/{conversation_id}/messages",
        json={"content": "my VPN keeps dropping"},
        headers=headers(a),
    )

    assert reply.status_code == 200 and "version 5" in reply.json()["reply"]
    history = (await client.get(f"/api/conversations/{conversation_id}/messages", headers=headers(a))).json()
    tool_message = next(m for m in history if m["role"] == "tool")
    assert (
        tool_message["tool_name"] == "search_knowledge_base"
        and "update the client" in tool_message["content"]
    )
