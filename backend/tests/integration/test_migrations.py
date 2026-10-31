"""Regression tests for the migration bugs recorded in ADR 0001 ("Bugs this surfaced")."""

import asyncio

import pytest
from alembic import command
from sqlalchemy import text

from app.config import APP_DB_ROLE
from app.db.session import AdminSessionLocal

from .conftest import alembic_config

pytestmark = pytest.mark.integration

ENUM_TYPES = {
    "system_status",
    "message_role",
    "ticket_category",
    "ticket_priority",
    "ticket_status",
    "escalation_status",
}


async def _existing_enums() -> set[str]:
    async with AdminSessionLocal() as session:
        rows = await session.scalars(text("SELECT typname FROM pg_type WHERE typtype = 'e'"))
        return set(rows)


async def _role_exists() -> bool:
    async with AdminSessionLocal() as session:
        query = text("SELECT 1 FROM pg_roles WHERE rolname = :r")
        return bool(await session.scalar(query, {"r": APP_DB_ROLE}))


async def _role_used_by_other_databases() -> bool:
    """Roles are cluster-wide: DROP ROLE fails while any *other* database on the
    server (e.g. the dev DB next to this test DB) still has grants to it."""
    async with AdminSessionLocal() as session:
        count = await session.scalar(
            text(
                "SELECT count(*) FROM pg_shdepend d JOIN pg_roles r ON r.oid = d.refobjid "
                "WHERE r.rolname = :r AND d.dbid NOT IN "
                "(0, (SELECT oid FROM pg_database WHERE datname = current_database()))"
            ),
            {"r": APP_DB_ROLE},
        )
    return bool(count)


async def test_downgrade_leaves_nothing_behind_and_upgrade_works_again():
    """upgrade -> downgrade -> upgrade. Catches leftover enum types (bug 4) and a
    role that cannot be dropped because of default privileges (bug 3).

    alembic's env.py uses asyncio.run(), so it runs in a worker thread here.
    """
    if await _role_used_by_other_databases():
        pytest.skip(f"another database on this server depends on role {APP_DB_ROLE}; runs in CI")
    cfg = alembic_config()
    await asyncio.to_thread(command.downgrade, cfg, "base")
    try:
        assert not (ENUM_TYPES & await _existing_enums())
        assert not await _role_exists()
    finally:
        await asyncio.to_thread(command.upgrade, cfg, "head")

    assert ENUM_TYPES <= await _existing_enums()
    assert await _role_exists()
