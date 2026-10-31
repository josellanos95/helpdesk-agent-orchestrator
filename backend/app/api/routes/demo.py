"""Demo entry: who can I be, start a session as that person, how much budget is left.

The directory and the session are the only unauthenticated routes besides /health and /tenants. They
read across tenants (to list every company and its people), which the RLS-restricted runtime role
cannot do, so they use the admin session on purpose and return nothing but what the entry screen shows.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy import func, select

from app.api.deps import Principal, client_ip, get_principal, get_redis, get_who
from app.config import get_settings
from app.db.models import Employee, KbArticle, Tenant
from app.db.session import AdminSessionLocal
from app.services import demo_token, limits
from app.services.limits import Who

router = APIRouter(prefix="/demo")


class PersonOut(BaseModel):
    id: uuid.UUID
    full_name: str
    job_title: str
    is_support_agent: bool


class CompanyOut(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    articles: int
    people: list[PersonOut]


class SessionIn(BaseModel):
    tenant_id: uuid.UUID
    employee_id: uuid.UUID


class SessionOut(BaseModel):
    token: str
    expires_at: datetime
    tenant: CompanyOut
    person: PersonOut
    role: str


class BudgetOut(BaseModel):
    """Remaining USD per scope; null means that cap is switched off."""

    session: Decimal | None
    ip: Decimal | None
    day: Decimal | None
    session_cap: Decimal | None


def _person(e: Employee) -> PersonOut:
    return PersonOut(
        id=e.id, full_name=e.full_name, job_title=e.job_title, is_support_agent=e.is_support_agent
    )


@router.get("/directory", response_model=list[CompanyOut])
async def directory() -> list[CompanyOut]:
    async with AdminSessionLocal() as session:
        tenants = (await session.scalars(select(Tenant).order_by(Tenant.name))).all()
        people = (await session.scalars(select(Employee).order_by(Employee.full_name))).all()
        counts = dict(
            (
                await session.execute(select(KbArticle.tenant_id, func.count()).group_by(KbArticle.tenant_id))
            ).all()
        )
    return [
        CompanyOut(
            id=t.id,
            name=t.name,
            slug=t.slug,
            articles=counts.get(t.id, 0),
            people=[_person(e) for e in people if e.tenant_id == t.id],
        )
        for t in tenants
    ]


@router.post("/session", response_model=SessionOut)
async def start_session(body: SessionIn, request: Request, redis: Redis = Depends(get_redis)) -> SessionOut:
    settings = get_settings()
    await limits.hit(redis, f"rl:session:ip:{client_ip(request)}", settings.sessions_per_hour_ip, 3600)

    async with AdminSessionLocal() as session:
        tenant = await session.get(Tenant, body.tenant_id)
        person = await session.get(Employee, body.employee_id)
        if tenant is None or person is None or person.tenant_id != tenant.id:
            raise HTTPException(status_code=404, detail="That person does not exist in that company.")
        company = CompanyOut(id=tenant.id, name=tenant.name, slug=tenant.slug, articles=0, people=[])
        out_person = _person(person)

    token, claims = demo_token.issue(
        settings.demo_token_secret,
        tenant_id=tenant.id,
        employee_id=person.id,
        ttl_seconds=settings.demo_token_ttl_hours * 3600,
    )
    return SessionOut(
        token=token,
        expires_at=datetime.fromtimestamp(claims.expires_at, UTC),
        tenant=company,
        person=out_person,
        role="support" if out_person.is_support_agent else "employee",
    )


@router.get("/budget", response_model=BudgetOut)
async def remaining_budget(
    principal: Principal = Depends(get_principal),
    who: Who = Depends(get_who),
    redis: Redis = Depends(get_redis),
) -> BudgetOut:
    state = await limits.budget(redis, get_settings(), who)
    cap = state.cap_usd.get("session")
    return BudgetOut(
        session=state.remaining("session"),
        ip=state.remaining("ip"),
        day=state.remaining("day"),
        session_cap=cap if cap and cap > 0 else None,
    )
