"""Automated version of the checks behind docs/adr/0001-multi-tenant-isolation-via-rls.md.

Everything here talks to a real Postgres: RLS is a database feature, so a mock
would prove nothing.
"""

import asyncio

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.db.session as session_module
from app.config import APP_DB_ROLE, get_settings
from app.db.models import TENANT_SCOPED_TABLES, Employee
from app.db.session import AdminSessionLocal

pytestmark = pytest.mark.integration


# --- Structure: the guarantees the migration is supposed to have set up ----------------------


async def test_runtime_role_cannot_bypass_rls():
    async with AdminSessionLocal() as session:
        row = (
            await session.execute(
                text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = :r"), {"r": APP_DB_ROLE}
            )
        ).one()
    assert row.rolsuper is False
    assert row.rolbypassrls is False


@pytest.mark.parametrize("table", TENANT_SCOPED_TABLES)
async def test_rls_is_enabled_forced_and_has_a_policy(table):
    async with AdminSessionLocal() as session:
        flags = (
            await session.execute(
                text("SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = :t"),
                {"t": table},
            )
        ).one()
        policies = (
            await session.execute(
                text("SELECT policyname FROM pg_policies WHERE tablename = :t"), {"t": table}
            )
        ).scalars().all()
    assert flags.relrowsecurity, f"{table}: RLS not enabled"
    assert flags.relforcerowsecurity, f"{table}: RLS not FORCEd (table owner would bypass it)"
    assert policies == ["tenant_isolation"]


async def test_every_table_with_a_tenant_id_is_registered_as_tenant_scoped():
    """ADR 0001 lists "add new tables to TENANT_SCOPED_TABLES" as a manual step.
    This turns that review-checklist item into a failing test."""
    async with AdminSessionLocal() as session:
        found = (
            await session.execute(
                text(
                    "SELECT table_name FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND column_name = 'tenant_id'"
                )
            )
        ).scalars().all()
    assert sorted(found) == sorted(TENANT_SCOPED_TABLES)


# --- Behaviour: what a tenant-scoped session can and cannot do -------------------------------


@pytest.mark.parametrize("table", TENANT_SCOPED_TABLES)
async def test_scoped_session_sees_only_its_own_rows(two_tenants, as_tenant, table):
    async with as_tenant(two_tenants.a.id) as session:
        tenant_ids = (await session.execute(text(f"SELECT tenant_id FROM {table}"))).scalars().all()
    assert tenant_ids == [two_tenants.a.id]


@pytest.mark.parametrize("table", TENANT_SCOPED_TABLES)
async def test_explicit_where_on_another_tenant_still_returns_nothing(two_tenants, as_tenant, table):
    """The adversarial case: the application *asks* for tenant B's rows."""
    async with as_tenant(two_tenants.a.id) as session:
        rows = (
            await session.execute(
                text(f"SELECT 1 FROM {table} WHERE tenant_id = :b"), {"b": two_tenants.b.id}
            )
        ).all()
    assert rows == []


async def test_cannot_insert_a_row_for_another_tenant(two_tenants, as_tenant):
    with pytest.raises(DBAPIError, match="row-level security"):
        async with as_tenant(two_tenants.a.id) as session:
            session.add(
                Employee(
                    tenant_id=two_tenants.b.id, full_name="Mallory", email="m@evil.test", job_title="Intruder"
                )
            )
            await session.flush()


async def test_cannot_move_a_row_to_another_tenant(two_tenants, as_tenant):
    with pytest.raises(DBAPIError, match="row-level security"):
        async with as_tenant(two_tenants.a.id) as session:
            await session.execute(
                text("UPDATE employees SET tenant_id = :b WHERE id = :e"),
                {"b": two_tenants.b.id, "e": two_tenants.a.employee_id},
            )


async def test_update_and_delete_cannot_touch_another_tenants_rows(two_tenants, as_tenant):
    async with as_tenant(two_tenants.a.id) as session:
        updated = await session.execute(
            text("UPDATE tickets SET subject = 'pwned' WHERE id = :t"), {"t": two_tenants.b.ticket_id}
        )
        deleted = await session.execute(
            text("DELETE FROM tickets WHERE id = :t"), {"t": two_tenants.b.ticket_id}
        )
    assert updated.rowcount == 0
    assert deleted.rowcount == 0

    async with AdminSessionLocal() as session:
        subject = await session.scalar(
            text("SELECT subject FROM tickets WHERE id = :t"), {"t": two_tenants.b.ticket_id}
        )
    assert subject == "Subject b"


async def test_session_without_a_tenant_never_returns_rows(two_tenants):
    """Forgetting to open a tenant_scoped_session must fail closed.

    On a connection that never had app.tenant_id set, current_setting(..., true)
    is NULL, so the policy matches nothing (zero rows, no error). Once any
    transaction on that connection has set it, it reads back as '' and the
    ::uuid cast raises instead — see the pooled-connection test below. Either
    way, no row is ever returned.
    """
    async with session_module.AppSessionLocal() as session:
        rows = (await session.execute(text("SELECT * FROM tickets"))).all()
    assert rows == []


# --- Connection pooling: the tenant must never outlive its transaction -----------------------


async def test_tenant_does_not_leak_into_the_next_request_on_the_same_connection(
    two_tenants, as_tenant, monkeypatch
):
    """Pool of exactly one connection, so request 2 is guaranteed to reuse request 1's."""
    engine = create_async_engine(
        get_settings().app_database_url, pool_size=1, max_overflow=0, pool_pre_ping=True
    )
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(session_module, "AppSessionLocal", sessionmaker)
    try:
        async with as_tenant(two_tenants.a.id) as session:
            assert (await session.execute(text("SELECT count(*) FROM tickets"))).scalar() == 1

        # Same connection, GUC now reads '' instead of NULL, so the ::uuid cast raises.
        async with sessionmaker() as session:
            with pytest.raises(DBAPIError, match="uuid"):
                await session.execute(text("SELECT * FROM tickets"))
    finally:
        await engine.dispose()


async def test_concurrent_requests_for_different_tenants_do_not_mix(two_tenants, as_tenant):
    async def count_visible(tenant_id):
        async with as_tenant(tenant_id) as session:
            await session.execute(text("SELECT pg_sleep(0.05)"))  # force the two to overlap
            return (await session.execute(text("SELECT DISTINCT tenant_id FROM tickets"))).scalars().all()

    results = await asyncio.gather(
        *[count_visible(t.id) for t in (two_tenants.a, two_tenants.b) * 5]
    )
    for tenant, seen in zip((two_tenants.a, two_tenants.b) * 5, results, strict=True):
        assert seen == [tenant.id]
