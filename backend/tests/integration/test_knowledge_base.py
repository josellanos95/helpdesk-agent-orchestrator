"""Ingesting and searching the knowledge base against a real Postgres + pgvector."""

import pytest
from sqlalchemy import func, select

import app.services.knowledge_base as kb
from app.db.models import EMBEDDING_DIMENSIONS, KbArticle, KbChunk
from app.db.session import AdminSessionLocal
from app.llm.embeddings import HashingEmbedder

pytestmark = pytest.mark.integration

EMB = HashingEmbedder()

VPN = (
    "VPN troubleshooting",
    "If the VPN client disconnects every few minutes, update the client to version 5 and turn off power "
    "saving on the wifi adapter.\n\nAfter updating, sign out of the VPN client and sign in again so that the "
    "certificate is refreshed. If it still drops, send the diagnostics log from the tray menu.",
)
MOBILE = (
    "Email on your phone",
    "To read work email on your phone install the Company Portal app, sign in with your work account and "
    "accept the device policy. Email appears within a few minutes.",
)
PAYROLL = (
    "Payroll portal access",
    "Payslips and tax documents live in the payroll portal. Sign in with single sign-on; if the page says "
    "you have no access, ask your manager to request the payroll role for you.",
)


async def ingest(as_tenant, tenant, article, *, embedder=EMB) -> KbArticle:
    prepared = await kb.prepare_article(embedder, *article)
    async with as_tenant(tenant.id) as session:
        return await kb.create_article(session, tenant.id, None, prepared)


async def search(as_tenant, tenant, query, *, embedder=EMB, **kwargs) -> list[kb.Hit]:
    async with as_tenant(tenant.id) as session:
        return await kb.search(session, embedder, query, **kwargs)


async def count(model, **where) -> int:
    async with AdminSessionLocal() as session:
        query = select(func.count()).select_from(model)
        for key, value in where.items():
            query = query.where(getattr(model, key) == value)
        return await session.scalar(query)


# ---------------------------------------------------------------------------- ingestion


async def test_an_article_is_chunked_embedded_and_stored(two_tenants, as_tenant):
    article = await ingest(as_tenant, two_tenants.a, VPN)

    async with AdminSessionLocal() as session:
        chunks = (
            await session.scalars(
                select(KbChunk).where(KbChunk.article_id == article.id).order_by(KbChunk.chunk_index)
            )
        ).all()
    assert [c.chunk_index for c in chunks] == list(range(len(chunks))) and chunks
    assert all(c.tenant_id == two_tenants.a.id and c.embedding_model == "hashing-v1" for c in chunks)
    assert all(len(c.embedding) == EMBEDDING_DIMENSIONS for c in chunks)
    assert article.content_hash == kb.content_hash("hashing-v1", *VPN)


async def test_the_same_title_cannot_be_used_twice_in_one_tenant_but_can_in_another(two_tenants, as_tenant):
    await ingest(as_tenant, two_tenants.a, VPN)
    with pytest.raises(kb.KbConflict, match="already exists"):
        await ingest(as_tenant, two_tenants.a, VPN)
    await ingest(as_tenant, two_tenants.b, VPN)  # a different company may use the same title


async def test_replacing_changes_the_content_and_the_passages(two_tenants, as_tenant):
    article = await ingest(as_tenant, two_tenants.a, VPN)
    new_body = "Use the new GlobalProtect client. Download it from the self-service catalogue and restart."
    prepared = await kb.prepare_article(EMB, VPN[0], new_body)

    async with as_tenant(two_tenants.a.id) as session:
        updated, changed = await kb.replace_article(session, article.id, prepared)

    assert changed is True and updated.body == new_body
    assert await count(KbChunk, article_id=article.id) == 1
    hits = await search(as_tenant, two_tenants.a, "GlobalProtect client download")
    assert hits and "GlobalProtect" in hits[0].content


async def test_saving_identical_content_is_a_no_op_and_keeps_the_stored_passages(two_tenants, as_tenant):
    article = await ingest(as_tenant, two_tenants.a, VPN)
    async with AdminSessionLocal() as session:
        before = {
            c.id for c in await session.scalars(select(KbChunk).where(KbChunk.article_id == article.id))
        }

    prepared = await kb.prepare_article(EMB, *VPN)
    async with as_tenant(two_tenants.a.id) as session:
        _, changed = await kb.replace_article(session, article.id, prepared)

    async with AdminSessionLocal() as session:
        after = {c.id for c in await session.scalars(select(KbChunk).where(KbChunk.article_id == article.id))}
    assert changed is False and before == after


async def test_renaming_onto_another_articles_title_is_a_conflict(two_tenants, as_tenant):
    await ingest(as_tenant, two_tenants.a, VPN)
    other = await ingest(as_tenant, two_tenants.a, MOBILE)
    prepared = await kb.prepare_article(EMB, VPN[0], "A completely different body for the second article.")
    with pytest.raises(kb.KbConflict, match="already titled"):
        async with as_tenant(two_tenants.a.id) as session:
            await kb.replace_article(session, other.id, prepared)


async def test_deleting_an_article_removes_its_passages(two_tenants, as_tenant):
    article = await ingest(as_tenant, two_tenants.a, VPN)
    async with as_tenant(two_tenants.a.id) as session:
        await kb.delete_article(session, article.id)
    assert await count(KbArticle, id=article.id) == 0 and await count(KbChunk, article_id=article.id) == 0
    with pytest.raises(kb.KbNotFound):
        async with as_tenant(two_tenants.a.id) as session:
            await kb.delete_article(session, article.id)


async def test_a_tenant_cannot_delete_or_replace_another_tenants_article(two_tenants, as_tenant):
    theirs = await ingest(as_tenant, two_tenants.b, VPN)
    with pytest.raises(kb.KbNotFound):
        async with as_tenant(two_tenants.a.id) as session:
            await kb.delete_article(session, theirs.id)
    prepared = await kb.prepare_article(EMB, "Hijack", "Replacement text written by another company.")
    with pytest.raises(kb.KbNotFound):
        async with as_tenant(two_tenants.a.id) as session:
            await kb.replace_article(session, theirs.id, prepared)
    assert await count(KbArticle, id=theirs.id) == 1


@pytest.mark.parametrize(
    ("title", "body", "message"),
    [
        ("ab", "A perfectly fine body of text for the article.", "title is too short"),
        ("Fine title", "   ", "no text"),
        ("Fine title", "x" * (kb.MAX_BODY_CHARS + 1), "too long"),
    ],
)
async def test_invalid_articles_are_rejected_before_any_embedding(title, body, message):
    class Exploding(HashingEmbedder):
        async def embed(self, texts):
            raise AssertionError("must not pay for embeddings of an invalid article")

    with pytest.raises(kb.KbInvalid, match=message):
        await kb.prepare_article(Exploding(), title, body)


async def test_an_article_needing_too_many_passages_is_rejected(monkeypatch):
    monkeypatch.setattr(kb, "MAX_CHUNKS_PER_ARTICLE", 2)
    body = "\n\n".join(f"Paragraph {i}. " + "word " * 120 for i in range(10))
    with pytest.raises(kb.KbInvalid, match="passages"):
        await kb.prepare_article(EMB, "Huge article", body)


async def test_a_tenant_cannot_exceed_the_article_cap(two_tenants, as_tenant, monkeypatch):
    monkeypatch.setattr(kb, "MAX_ARTICLES_PER_TENANT", 1)  # the fixture already stored one
    with pytest.raises(kb.KbConflict, match="full"):
        await ingest(as_tenant, two_tenants.a, VPN)


# ------------------------------------------------------------------------------ search


async def test_the_most_relevant_article_comes_first(two_tenants, as_tenant):
    for article in (MOBILE, VPN, PAYROLL):
        await ingest(as_tenant, two_tenants.a, article)

    hits = await search(as_tenant, two_tenants.a, "VPN client disconnects every few minutes")
    assert hits[0].title == "VPN troubleshooting"
    assert hits[0].keyword_match is True  # every word of the question is in the passage

    hits = await search(as_tenant, two_tenants.a, "install the company portal app for work email")
    assert hits[0].title == "Email on your phone"


async def test_a_word_missing_from_the_passage_does_not_hide_it_from_the_ranking(two_tenants, as_tenant):
    """Natural questions contain words the article never uses ("keeps"). Ranking by how many words
    match, instead of requiring all of them, still puts the right article first."""
    for article in (MOBILE, VPN, PAYROLL):
        await ingest(as_tenant, two_tenants.a, article)

    hits = await search(as_tenant, two_tenants.a, "my VPN keeps disconnecting", min_similarity=0.0)
    assert hits[0].title == "VPN troubleshooting"


async def test_a_coincidental_common_word_is_not_enough_to_pass_the_relevance_gate(two_tenants, as_tenant):
    await ingest(as_tenant, two_tenants.a, VPN)  # contains the word "minutes"
    assert await search(as_tenant, two_tenants.a, "chocolate cake minutes") == []


async def test_an_unrelated_question_returns_nothing_instead_of_the_nearest_neighbour(two_tenants, as_tenant):
    """A nearest neighbour always exists; without the relevance gate the agent would be handed noise."""
    await ingest(as_tenant, two_tenants.a, VPN)
    await ingest(as_tenant, two_tenants.a, MOBILE)
    assert await search(as_tenant, two_tenants.a, "recipe for chocolate cake with strawberries") == []


async def test_a_word_match_is_found_even_when_the_embedding_does_not_agree(two_tenants, as_tenant):
    """The reason for hybrid search: an exact term (an error code, a product name) the embedding blurs."""
    article = await ingest(as_tenant, two_tenants.a, MOBILE)
    async with as_tenant(two_tenants.a.id) as session:
        session.add(
            KbChunk(
                tenant_id=two_tenants.a.id,
                article_id=article.id,
                chunk_index=99,
                content="Error ZEBRACORN-4417 means the licence server is unreachable.",
                embedding_model=EMB.model,
                embedding=[0.0, 1.0] + [0.0] * (EMBEDDING_DIMENSIONS - 2),  # unrelated to any query
            )
        )

    hits = await search(as_tenant, two_tenants.a, "ZEBRACORN-4417")
    assert [h.content for h in hits] == ["Error ZEBRACORN-4417 means the licence server is unreachable."]
    assert hits[0].keyword_match is True and hits[0].similarity < 0.3


async def test_tenants_never_see_each_others_passages_even_when_the_other_matches_better(
    two_tenants, as_tenant
):
    """With an approximate global index and post-filtering, a closer foreign chunk would crowd out
    the caller's own results. Exact search under RLS must still return the caller's best matches."""
    await ingest(as_tenant, two_tenants.a, VPN)
    for n in range(8):  # B has many chunks that match the query word for word
        await ingest(
            as_tenant,
            two_tenants.b,
            (f"B secret {n}", "my VPN keeps disconnecting every few minutes " * 6),
        )

    hits = await search(
        as_tenant, two_tenants.a, "my VPN keeps disconnecting every few minutes", top_k=4, min_similarity=0.0
    )
    assert hits and {h.title for h in hits} == {"VPN troubleshooting"}


async def test_vectors_from_a_different_model_are_never_compared(two_tenants, as_tenant):
    article = await ingest(as_tenant, two_tenants.a, MOBILE)
    query_vector = (await EMB.embed(["install the company portal app"]))[0]
    async with as_tenant(two_tenants.a.id) as session:
        session.add(
            KbChunk(
                tenant_id=two_tenants.a.id,
                article_id=article.id,
                chunk_index=50,
                content="Chunk embedded by some other model entirely.",
                embedding_model="some-other-model",
                embedding=query_vector,  # a perfect match, but from the wrong vector space
            )
        )
    hits = await search(as_tenant, two_tenants.a, "install the company portal app")
    assert "some other model" not in " ".join(h.content for h in hits)


async def test_one_long_article_cannot_fill_every_slot(two_tenants, as_tenant):
    long_body = "\n\n".join(
        f"VPN disconnects part {i}. " + "the vpn client disconnects often " * 18 for i in range(8)
    )
    await ingest(as_tenant, two_tenants.a, ("Long VPN article", long_body))
    await ingest(as_tenant, two_tenants.a, VPN)

    hits = await search(as_tenant, two_tenants.a, "vpn client disconnects", top_k=5)
    titles = [h.title for h in hits]
    assert titles.count("Long VPN article") <= kb.MAX_CHUNKS_PER_ARTICLE_IN_RESULTS
    assert "VPN troubleshooting" in titles


async def test_top_k_is_respected(two_tenants, as_tenant):
    for n in range(6):
        await ingest(
            as_tenant,
            two_tenants.a,
            (f"VPN note {n}", f"The VPN client note number {n} explains disconnects."),
        )
    assert len(await search(as_tenant, two_tenants.a, "vpn client disconnects", top_k=3)) == 3


@pytest.mark.parametrize(
    "query",
    [
        "'; DROP TABLE kb_chunks; --",
        "&|!()<>:*",
        '"unbalanced quote',
        "a " * 150,
        "emoji 🔥 and 日本語 text",
        "the and of to",  # only stop words: the full-text side matches nothing
    ],
)
async def test_hostile_or_odd_queries_do_not_break_search(two_tenants, as_tenant, query):
    await ingest(as_tenant, two_tenants.a, VPN)
    assert isinstance(await search(as_tenant, two_tenants.a, query), list)
    assert await count(KbChunk, tenant_id=two_tenants.a.id) >= 1  # the table survived
