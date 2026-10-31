"""The tenant knowledge base: ingest articles, search them.

Search is hybrid. The query is matched by meaning (cosine similarity of embeddings) and by words
(Postgres full-text, ranked by how many query words a passage has); the two ranked lists are merged
with Reciprocal Rank Fusion, so a chunk that is
good on either axis surfaces and one that is good on both wins. Words rescue exact terms the embedding
blurs (a product name, an error code); embeddings rescue paraphrases the words miss.

Tenant isolation is not re-implemented here: every query runs in a tenant-scoped session, so Row Level
Security limits what exists to the caller's own articles.

Expensive work (chunking, embedding) happens *before* any transaction is opened (`prepare_article`),
so no database connection is held while a network call is in flight.
"""

import hashlib
import uuid
from dataclasses import dataclass

from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import KbArticle, KbChunk
from app.llm.embeddings import Embedder
from app.services.chunking import chunk_text

MAX_ARTICLES_PER_TENANT = 100
MAX_BODY_CHARS = 20_000
MAX_CHUNKS_PER_ARTICLE = 40
RRF_K = 60  # the usual constant: damps the weight of the very top ranks
CANDIDATES = 30  # how many from each ranking enter the fusion
MAX_CHUNKS_PER_ARTICLE_IN_RESULTS = 2


class KbError(Exception):
    status_code = 400

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class KbInvalid(KbError):
    status_code = 422


class KbConflict(KbError):
    status_code = 409


class KbNotFound(KbError):
    status_code = 404


@dataclass(frozen=True)
class PreparedChunk:
    index: int
    text: str
    embedding: list[float]


@dataclass(frozen=True)
class PreparedArticle:
    title: str
    body: str
    content_hash: str
    embedding_model: str
    chunks: list[PreparedChunk]


@dataclass(frozen=True)
class Hit:
    chunk_id: uuid.UUID
    article_id: uuid.UUID
    title: str
    content: str
    chunk_index: int
    similarity: float | None  # None when only the keyword ranking found it
    keyword_match: bool  # every word of the query appears in the passage
    score: float


def content_hash(model: str, title: str, body: str) -> str:
    return hashlib.sha256(f"{model}\n{title}\n{body}".encode()).hexdigest()


async def prepare_article(embedder: Embedder, title: str, body: str) -> PreparedArticle:
    """Validate, chunk and embed. Touches the network, never the database."""
    title, body = title.strip(), body.strip()
    if len(title) < 3:
        raise KbInvalid("The title is too short.")
    if len(body) > MAX_BODY_CHARS:
        raise KbInvalid(f"The article is too long ({len(body)} characters, the limit is {MAX_BODY_CHARS}).")
    pieces = chunk_text(body)
    if not pieces:
        raise KbInvalid("The article has no text.")
    if len(pieces) > MAX_CHUNKS_PER_ARTICLE:
        raise KbInvalid(
            f"The article would need {len(pieces)} passages (the limit is {MAX_CHUNKS_PER_ARTICLE})."
        )

    # The title travels with every chunk so "reset steps" is understood as being about *this* article.
    embeddings = await embedder.embed([f"{title}\n\n{piece}" for piece in pieces])
    return PreparedArticle(
        title=title,
        body=body,
        content_hash=content_hash(embedder.model, title, body),
        embedding_model=embedder.model,
        chunks=[
            PreparedChunk(i, piece, vec)
            for i, (piece, vec) in enumerate(zip(pieces, embeddings, strict=True))
        ],
    )


def _add_chunks(
    session: AsyncSession, tenant_id: uuid.UUID, article_id: uuid.UUID, prepared: PreparedArticle
) -> None:
    for chunk in prepared.chunks:
        session.add(
            KbChunk(
                tenant_id=tenant_id,
                article_id=article_id,
                chunk_index=chunk.index,
                content=chunk.text,
                embedding_model=prepared.embedding_model,
                embedding=chunk.embedding,
            )
        )


async def create_article(
    session: AsyncSession, tenant_id: uuid.UUID, author_id: uuid.UUID | None, prepared: PreparedArticle
) -> KbArticle:
    count = await session.scalar(select(func.count()).select_from(KbArticle))
    if count >= MAX_ARTICLES_PER_TENANT:
        raise KbConflict(f"This knowledge base is full ({MAX_ARTICLES_PER_TENANT} articles).")

    article_id = await session.scalar(
        pg_insert(KbArticle)
        .values(
            tenant_id=tenant_id,
            title=prepared.title,
            body=prepared.body,
            content_hash=prepared.content_hash,
            created_by=author_id,
        )
        .on_conflict_do_nothing(index_elements=["tenant_id", "title"])
        .returning(KbArticle.id)
    )
    if article_id is None:
        raise KbConflict(f"An article titled '{prepared.title}' already exists. Update it instead.")
    _add_chunks(session, tenant_id, article_id, prepared)
    await session.flush()
    return await session.get(KbArticle, article_id)


async def replace_article(
    session: AsyncSession, article_id: uuid.UUID, prepared: PreparedArticle
) -> tuple[KbArticle, bool]:
    """Returns (article, changed). Identical content is a no-op: nothing is re-stored."""
    article = await session.scalar(select(KbArticle).where(KbArticle.id == article_id).with_for_update())
    if article is None:
        raise KbNotFound("Article not found")
    if article.content_hash == prepared.content_hash and article.title == prepared.title:
        return article, False

    clash = await session.scalar(
        select(KbArticle.id).where(KbArticle.title == prepared.title, KbArticle.id != article_id)
    )
    if clash is not None:
        raise KbConflict(f"Another article is already titled '{prepared.title}'.")

    await session.execute(delete(KbChunk).where(KbChunk.article_id == article_id))
    article.title = prepared.title
    article.body = prepared.body
    article.content_hash = prepared.content_hash
    _add_chunks(session, article.tenant_id, article_id, prepared)
    await session.flush()
    await session.refresh(article)
    return article, True


async def delete_article(session: AsyncSession, article_id: uuid.UUID) -> None:
    deleted = await session.scalar(
        delete(KbArticle).where(KbArticle.id == article_id).returning(KbArticle.id)
    )
    if deleted is None:
        raise KbNotFound("Article not found")


_SEARCH_SQL = text(
    """
    WITH q AS (
        -- plainto_tsquery cannot raise on odd input and returns 'a' & 'b'; swapping & for | gives a
        -- query that ranks chunks by how many of the words they contain, not by demanding all of them.
        SELECT CAST(:qvec AS vector) AS v,
               plainto_tsquery('english', :qtext) AS t_all,
               replace(plainto_tsquery('english', :qtext)::text, ' & ', ' | ')::tsquery AS t_any
    ),
    vec AS (
        SELECT c.id,
               1 - (c.embedding <=> q.v) AS sim,
               row_number() OVER (ORDER BY c.embedding <=> q.v) AS rnk
        FROM kb_chunks c, q
        WHERE c.embedding_model = :model
        ORDER BY c.embedding <=> q.v
        LIMIT :cand
    ),
    fts AS (
        SELECT c.id,
               row_number() OVER (ORDER BY ts_rank_cd(c.tsv, q.t_any) DESC) AS rnk
        FROM kb_chunks c, q
        WHERE c.embedding_model = :model AND c.tsv @@ q.t_any
        ORDER BY ts_rank_cd(c.tsv, q.t_any) DESC
        LIMIT :cand
    )
    SELECT c.id AS chunk_id, c.article_id, a.title, c.content, c.chunk_index,
           vec.sim AS similarity,
           -- strict on purpose: ALL the query's words are in the chunk (the relevance gate uses this)
           (c.tsv @@ q.t_all) AS keyword_match,
           COALESCE(1.0 / (:rrf + vec.rnk), 0) + COALESCE(1.0 / (:rrf + fts.rnk), 0) AS score
    FROM kb_chunks c
    CROSS JOIN q
    JOIN kb_articles a ON a.id = c.article_id
    LEFT JOIN vec ON vec.id = c.id
    LEFT JOIN fts ON fts.id = c.id
    WHERE vec.id IS NOT NULL OR fts.id IS NOT NULL
    ORDER BY score DESC
    LIMIT :fetch
    """
)


def _vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{v:.7g}" for v in vector) + "]"


async def search_by_vector(
    session: AsyncSession,
    vector: list[float],
    query_text: str,
    *,
    model: str,
    top_k: int = 4,
    min_similarity: float = 0.3,
) -> list[Hit]:
    """Hybrid search with an already-embedded query (so the caller can embed outside a transaction)."""
    rows = (
        await session.execute(
            _SEARCH_SQL,
            {
                "qvec": _vector_literal(vector),
                "qtext": query_text,
                "model": model,
                "cand": CANDIDATES,
                "rrf": RRF_K,
                "fetch": top_k * 4,
            },
        )
    ).all()

    hits: list[Hit] = []
    per_article: dict[uuid.UUID, int] = {}
    for row in rows:
        # Relevance gate: a nearest neighbour always exists, so closeness alone proves nothing.
        # Keep it if it is close enough in meaning OR contains the query's words.
        if not (row.keyword_match or (row.similarity is not None and row.similarity >= min_similarity)):
            continue
        if per_article.get(row.article_id, 0) >= MAX_CHUNKS_PER_ARTICLE_IN_RESULTS:
            continue  # one long article should not crowd out every other source
        per_article[row.article_id] = per_article.get(row.article_id, 0) + 1
        hits.append(
            Hit(
                chunk_id=row.chunk_id,
                article_id=row.article_id,
                title=row.title,
                content=row.content,
                chunk_index=row.chunk_index,
                similarity=float(row.similarity) if row.similarity is not None else None,
                keyword_match=row.keyword_match,
                score=float(row.score),
            )
        )
        if len(hits) == top_k:
            break
    return hits


async def search(
    session: AsyncSession, embedder: Embedder, query: str, *, top_k: int = 4, min_similarity: float = 0.3
) -> list[Hit]:
    [vector] = await embedder.embed([query])
    return await search_by_vector(
        session, vector, query, model=embedder.model, top_k=top_k, min_similarity=min_similarity
    )
