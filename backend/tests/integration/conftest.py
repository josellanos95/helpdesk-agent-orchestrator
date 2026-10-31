import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

import pytest
import redis.asyncio as redis
from alembic import command
from alembic.config import Config
from sqlalchemy import delete

from app.config import get_settings
from app.db.models import (
    AgentRun,
    AgentStep,
    Conversation,
    Employee,
    Escalation,
    IdempotencyKey,
    Message,
    MessageRole,
    System,
    Tenant,
    Ticket,
    TicketCategory,
    TicketEvent,
    ToolExecution,
)
from app.db.session import AdminSessionLocal, admin_engine, app_engine, tenant_scoped_session

BACKEND_DIR = Path(__file__).resolve().parents[2]


def alembic_config() -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    return cfg


@pytest.fixture(scope="session", autouse=True)
def migrated_database() -> None:
    """Bring the test database to head once per session.

    Sync on purpose: migrations/env.py calls asyncio.run(), which cannot nest
    inside a running event loop.
    """
    command.upgrade(alembic_config(), "head")


@pytest.fixture(autouse=True)
async def _dispose_engines() -> AsyncIterator[None]:
    """asyncpg connections are bound to the event loop that opened them, and
    pytest-asyncio gives every test its own loop — so drop the pools after each test."""
    yield
    await admin_engine.dispose()
    await app_engine.dispose()


@pytest.fixture
def as_tenant():
    """`async with as_tenant(tenant_id) as session:` — see _as_tenant."""
    return _as_tenant


@asynccontextmanager
async def _as_tenant(tenant_id: uuid.UUID):
    """Drive the real `tenant_scoped_session` generator as a context manager.

    Unlike `async for`, this lets the generator see the test body's exception
    (so `session.begin()` rolls back deterministically) and always finishes it.
    """
    gen = tenant_scoped_session(tenant_id)
    session = await gen.__anext__()
    try:
        yield session
    except BaseException as exc:
        try:
            await gen.athrow(exc)
        except StopAsyncIteration:
            pass
        raise
    else:
        try:
            await gen.__anext__()
        except StopAsyncIteration:
            pass


@dataclass
class TenantData:
    id: uuid.UUID
    ticket_id: uuid.UUID
    employee_id: uuid.UUID
    conversation_id: uuid.UUID


@dataclass
class TwoTenants:
    a: TenantData
    b: TenantData


async def _create_tenant_with_rows(session, label: str) -> TenantData:
    tenant = Tenant(name=f"Test {label}", slug=f"test-{label}-{uuid.uuid4().hex[:8]}")
    session.add(tenant)
    await session.flush()

    employee = Employee(
        tenant_id=tenant.id, full_name=f"Emp {label}", email=f"{label}@example.test", job_title="Tester"
    )
    session.add(employee)
    session.add(System(tenant_id=tenant.id, name=f"VPN {label}"))
    await session.flush()

    conversation = Conversation(tenant_id=tenant.id, employee_id=employee.id)
    session.add(conversation)
    await session.flush()

    session.add(
        Message(tenant_id=tenant.id, conversation_id=conversation.id, role=MessageRole.user, content="hi")
    )
    ticket = Ticket(
        tenant_id=tenant.id,
        conversation_id=conversation.id,
        employee_id=employee.id,
        category=TicketCategory.network,
        subject=f"Subject {label}",
        description="desc",
    )
    session.add(ticket)
    await session.flush()

    session.add(TicketEvent(tenant_id=tenant.id, ticket_id=ticket.id, event_type="created", payload={}))
    session.add(Escalation(tenant_id=tenant.id, ticket_id=ticket.id, reason="because"))

    run = AgentRun(tenant_id=tenant.id, conversation_id=conversation.id, model="test-model")
    session.add(run)
    await session.flush()
    session.add(
        AgentStep(tenant_id=tenant.id, run_id=run.id, step_index=0, kind="llm", name="test-model")
    )
    session.add(
        ToolExecution(
            tenant_id=tenant.id,
            conversation_id=conversation.id,
            tool_call_id="fixture-call",
            tool_name="check_system_status",
            arguments="{}",
            result={},
        )
    )
    session.add(
        IdempotencyKey(tenant_id=tenant.id, key="fixture-key", request_hash="x", status="completed")
    )
    await session.flush()
    return TenantData(
        id=tenant.id, ticket_id=ticket.id, employee_id=employee.id, conversation_id=conversation.id
    )


@pytest.fixture
async def two_tenants() -> AsyncIterator[TwoTenants]:
    """Two tenants, each with exactly one row in every tenant-scoped table.

    Created through the ADMIN session (the runtime role cannot write across
    tenants) and removed afterwards; deleting the tenant cascades.
    """
    async with AdminSessionLocal() as session:
        a = await _create_tenant_with_rows(session, "a")
        b = await _create_tenant_with_rows(session, "b")
        await session.commit()
    try:
        yield TwoTenants(a=a, b=b)
    finally:
        async with AdminSessionLocal() as session:
            await session.execute(delete(Tenant).where(Tenant.id.in_([a.id, b.id])))
            await session.commit()


@pytest.fixture
async def redis_client() -> AsyncIterator[redis.Redis]:
    """A client for the test Redis database (15), emptied before and after each test."""
    client = redis.Redis.from_url(get_settings().redis_url, decode_responses=True)
    await client.flushdb()
    yield client
    await client.flushdb()
    await client.aclose()
