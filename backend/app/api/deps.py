import uuid
from collections.abc import AsyncGenerator

from fastapi import Depends, Header, HTTPException
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.redis_client import get_redis_client
from app.db.models import Employee
from app.db.session import tenant_scoped_session
from app.llm.base import LLMClient
from app.llm.embeddings import Embedder, build_embedder
from app.llm.openai_client import OpenAIClient

TENANT_HEADER = "X-Tenant-Id"


async def get_tenant_id(x_tenant_id: str = Header(..., alias=TENANT_HEADER)) -> uuid.UUID:
    try:
        return uuid.UUID(x_tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid {TENANT_HEADER} header") from exc


async def get_db(tenant_id: uuid.UUID = Depends(get_tenant_id)) -> AsyncGenerator[AsyncSession]:
    async for session in tenant_scoped_session(tenant_id):
        yield session


def get_llm() -> LLMClient:
    """Overridden in tests with a scripted client. M8 adds per-request bring-your-own-key here."""
    settings = get_settings()
    if not settings.openai_api_key:
        raise HTTPException(status_code=503, detail="The LLM is not configured (OPENAI_API_KEY is missing).")
    return OpenAIClient(
        api_key=settings.openai_api_key,
        model=settings.openai_model,
        base_url=settings.openai_base_url,
    )


def get_redis() -> Redis:
    """Overridden in tests so each test gets a client bound to its own event loop."""
    return get_redis_client()


def get_embedder() -> Embedder | None:
    """None when no embedding provider is configured; callers decide how to degrade."""
    return build_embedder(get_settings())


async def support_agent_or_403(session: AsyncSession, employee_id: uuid.UUID) -> Employee:
    """Who may change shared state (approvals, escalations, the knowledge base): support agents."""
    agent = await session.get(Employee, employee_id)
    if agent is None or not agent.is_support_agent:
        raise HTTPException(status_code=403, detail="Only support agents can do that.")
    return agent
