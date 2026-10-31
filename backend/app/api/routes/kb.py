"""Managing and searching the knowledge base.

Writing needs a support agent of the tenant (claimed in the request until real authentication exists, as
for approvals). Searching is open to the tenant: it is what the agent does for employees.
"""

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_embedder, get_tenant_id, support_agent_or_403
from app.config import get_settings
from app.db.models import KbArticle, KbChunk
from app.db.session import tenant_session
from app.llm.embeddings import Embedder
from app.services import knowledge_base as kb

router = APIRouter(prefix="/kb")


class ArticleIn(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    body: str = Field(min_length=20, max_length=kb.MAX_BODY_CHARS)
    author_id: uuid.UUID


class ArticleOut(BaseModel):
    id: uuid.UUID
    title: str
    passages: int
    updated_at: datetime
    body: str | None = None


class ReplaceOut(BaseModel):
    article: ArticleOut
    changed: bool


class SearchIn(BaseModel):
    query: str = Field(min_length=3, max_length=300)
    top_k: int = Field(default=4, ge=1, le=8)


class HitOut(BaseModel):
    article_id: uuid.UUID
    article: str
    passage: str
    similarity: float | None
    keyword_match: bool
    score: float


def _require_embedder(embedder: Embedder | None) -> Embedder:
    if embedder is None:
        raise HTTPException(503, "Embeddings are not configured (set OPENAI_API_KEY or EMBEDDING_PROVIDER).")
    return embedder


async def _article_out(session: AsyncSession, article: KbArticle, *, with_body: bool = False) -> ArticleOut:
    passages = await session.scalar(
        select(func.count()).select_from(KbChunk).where(KbChunk.article_id == article.id)
    )
    return ArticleOut(
        id=article.id,
        title=article.title,
        passages=passages,
        updated_at=article.updated_at,
        body=article.body if with_body else None,
    )


@router.get("/articles", response_model=list[ArticleOut])
async def list_articles(session: AsyncSession = Depends(get_db)) -> list[ArticleOut]:
    articles = await session.scalars(select(KbArticle).order_by(KbArticle.title))
    return [await _article_out(session, a) for a in articles]


@router.get("/articles/{article_id}", response_model=ArticleOut)
async def get_article(article_id: uuid.UUID, session: AsyncSession = Depends(get_db)) -> ArticleOut:
    article = await session.get(KbArticle, article_id)
    if article is None:
        raise HTTPException(404, "Article not found")
    return await _article_out(session, article, with_body=True)


@router.post("/articles", response_model=ArticleOut, status_code=201)
async def create_article(
    body: ArticleIn,
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    embedder: Embedder | None = Depends(get_embedder),
) -> ArticleOut:
    embedder = _require_embedder(embedder)
    async with tenant_session(tenant_id) as session:
        await support_agent_or_403(session, body.author_id)
    try:
        prepared = await kb.prepare_article(embedder, body.title, body.body)  # network, no transaction open
        async with tenant_session(tenant_id) as session:
            article = await kb.create_article(session, tenant_id, body.author_id, prepared)
            return await _article_out(session, article)
    except kb.KbError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc


@router.put("/articles/{article_id}", response_model=ReplaceOut)
async def replace_article(
    article_id: uuid.UUID,
    body: ArticleIn,
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    embedder: Embedder | None = Depends(get_embedder),
) -> ReplaceOut:
    embedder = _require_embedder(embedder)
    async with tenant_session(tenant_id) as session:
        await support_agent_or_403(session, body.author_id)
        current = await session.get(KbArticle, article_id)
        if current is None:
            raise HTTPException(404, "Article not found")
        # Identical content is detected from the hash alone, before paying for any embedding.
        unchanged = current.title == body.title.strip() and current.content_hash == kb.content_hash(
            embedder.model, body.title.strip(), body.body.strip()
        )
        if unchanged:
            return ReplaceOut(article=await _article_out(session, current), changed=False)
    try:
        prepared = await kb.prepare_article(embedder, body.title, body.body)
        async with tenant_session(tenant_id) as session:
            article, changed = await kb.replace_article(session, article_id, prepared)
            return ReplaceOut(article=await _article_out(session, article), changed=changed)
    except kb.KbError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc


@router.delete("/articles/{article_id}", status_code=204)
async def delete_article(
    article_id: uuid.UUID, actor_id: uuid.UUID, tenant_id: uuid.UUID = Depends(get_tenant_id)
) -> Response:
    async with tenant_session(tenant_id) as session:
        await support_agent_or_403(session, actor_id)
        try:
            await kb.delete_article(session, article_id)
        except kb.KbError as exc:
            raise HTTPException(exc.status_code, exc.detail) from exc
    return Response(status_code=204)


@router.post("/search", response_model=list[HitOut])
async def search(
    body: SearchIn,
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    embedder: Embedder | None = Depends(get_embedder),
    detail: Literal["full", "short"] = Query("short"),
) -> list[HitOut]:
    embedder = _require_embedder(embedder)
    [vector] = await embedder.embed([body.query])  # no transaction open while this runs
    async with tenant_session(tenant_id) as session:
        hits = await kb.search_by_vector(
            session,
            vector,
            body.query,
            model=embedder.model,
            top_k=body.top_k,
            min_similarity=get_settings().kb_min_similarity,
        )
    return [
        HitOut(
            article_id=h.article_id,
            article=h.title,
            passage=h.content if detail == "full" else h.content[:300],
            similarity=h.similarity,
            keyword_match=h.keyword_match,
            score=h.score,
        )
        for h in hits
    ]
