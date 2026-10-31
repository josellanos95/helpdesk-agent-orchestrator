import uuid
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings

settings = get_settings()

# Owner/superuser connection — bypasses RLS. Migrations and seed scripts only.
admin_engine = create_async_engine(settings.admin_database_url, pool_pre_ping=True)
AdminSessionLocal = async_sessionmaker(admin_engine, expire_on_commit=False)

# app_runtime connection — RLS-enforced. Everything request-scoped uses this.
app_engine = create_async_engine(settings.app_database_url, pool_pre_ping=True)
AppSessionLocal = async_sessionmaker(app_engine, expire_on_commit=False)


async def get_admin_db() -> AsyncGenerator[AsyncSession]:
    """Bypasses Row Level Security. Only for seeding/admin scripts — never wire into request routes."""
    async with AdminSessionLocal() as session:
        yield session


@asynccontextmanager
async def tenant_session(tenant_id: uuid.UUID) -> AsyncIterator[AsyncSession]:
    """One RLS-enforced transaction scoped to one tenant: commits on exit, rolls back on error.

    Uses set_config(..., true) rather than `SET LOCAL app.tenant_id = :tid` —
    Postgres doesn't accept a bind parameter there (it's not a plain function
    call), so asyncpg's prepared-statement protocol rejects it. set_config()
    is a regular function and the `true` (is_local) argument gives the same
    transaction-scoped lifetime as SET LOCAL: it never survives past the
    transaction, so there is no risk of a tenant_id leaking into a later
    request that reuses the same pooled connection.

    Keep these short. Code that waits on something slow (an LLM call) must not sit inside one:
    the transaction holds a pooled connection for as long as it is open.
    """
    async with AppSessionLocal() as session, session.begin():
        await session.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": str(tenant_id)}
        )
        yield session


async def tenant_scoped_session(tenant_id: uuid.UUID) -> AsyncGenerator[AsyncSession]:
    """FastAPI-dependency flavour of `tenant_session` (one transaction for the whole request)."""
    async with tenant_session(tenant_id) as session:
        yield session
