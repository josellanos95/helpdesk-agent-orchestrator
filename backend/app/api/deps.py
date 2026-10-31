import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.redis_client import get_redis_client
from app.db.models import Employee
from app.db.session import tenant_scoped_session
from app.llm.base import LLMClient
from app.llm.embeddings import Embedder, build_embedder
from app.llm.openai_client import OpenAIClient
from app.services import demo_token
from app.services.limits import Who

TENANT_HEADER = "X-Tenant-Id"


@dataclass(frozen=True)
class Principal:
    """Who is calling. `employee_id` is None only in header mode, where nobody is authenticated and the
    old rules apply (the body names the actor). With a signed token it is always set and the server
    enforces what that person may see and do."""

    tenant_id: uuid.UUID
    employee_id: uuid.UUID | None
    session_id: str | None
    ip: str


def client_ip(request: Request) -> str:
    if get_settings().trust_forwarded_for:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded.strip():
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _bearer(authorization: str | None) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip() or None
    return None


async def get_principal(
    request: Request,
    authorization: str | None = Header(default=None),
    x_tenant_id: str | None = Header(default=None, alias=TENANT_HEADER),
) -> Principal:
    settings = get_settings()
    ip = client_ip(request)
    token = _bearer(authorization)

    if token and settings.demo_token_secret:
        try:
            claims = demo_token.verify(settings.demo_token_secret, token)
        except demo_token.InvalidToken as exc:
            raise HTTPException(
                status_code=401, detail="Your demo session is invalid or expired. Choose a person again."
            ) from exc
        return Principal(claims.tenant_id, claims.employee_id, claims.session_id, ip)

    if settings.auth_mode == "signed":
        raise HTTPException(status_code=401, detail="Choose a person to start a demo session.")

    # Header mode (development, tests): the caller names the tenant and nobody is authenticated.
    if x_tenant_id is None:
        raise HTTPException(status_code=422, detail=f"Missing {TENANT_HEADER} header")
    try:
        return Principal(uuid.UUID(x_tenant_id), None, None, ip)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid {TENANT_HEADER} header") from exc


async def get_tenant_id(principal: Principal = Depends(get_principal)) -> uuid.UUID:
    return principal.tenant_id


def get_who(principal: Principal = Depends(get_principal)) -> Who:
    return Who(tenant_id=principal.tenant_id, ip=principal.ip, session_id=principal.session_id)


@dataclass(frozen=True)
class Actor:
    """The signed-in person as the database knows them. `restricted` is False in header mode, where the
    caller is trusted to name anyone (the historical behaviour, kept for development and tests)."""

    id: uuid.UUID | None
    support: bool
    restricted: bool

    def may_see_all(self) -> bool:
        return not self.restricted or self.support


async def actor_for(session: AsyncSession, principal: Principal) -> Actor:
    if principal.employee_id is None:
        return Actor(id=None, support=True, restricted=False)
    employee = await session.get(Employee, principal.employee_id)
    if employee is None:  # the person was deleted after the token was issued
        raise HTTPException(status_code=401, detail="This demo session no longer matches a person.")
    return Actor(id=employee.id, support=employee.is_support_agent, restricted=True)


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
