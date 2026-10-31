"""Test harness.

Tests never touch the development database. `pytest_configure` derives a
sibling database named `<dbname>_test` from DATABASE_URL, creates it if
missing, and points the app at it *before* any `app.*` module is imported
(engines are created at import time in app/db/session.py).
"""

import asyncio
import os

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

DEFAULT_DATABASE_URL = "postgresql+asyncpg://helpdesk:helpdesk@localhost:5432/helpdesk"


def _test_database_url() -> str:
    url = make_url(os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL))
    name = url.database or "helpdesk"
    if not name.endswith("_test"):
        name = f"{name}_test"
    return url.set(drivername="postgresql+asyncpg", database=name).render_as_string(hide_password=False)


async def _ensure_database(url_str: str) -> None:
    url = make_url(url_str)
    # CREATE DATABASE cannot run inside a transaction block.
    engine = create_async_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            query = text("SELECT 1 FROM pg_database WHERE datname = :n")
            exists = await conn.scalar(query, {"n": url.database})
            if not exists:
                await conn.execute(text(f'CREATE DATABASE "{url.database}"'))
    finally:
        await engine.dispose()


def _test_redis_url() -> str:
    """Same server as REDIS_URL but database 15, which the tests flush freely."""
    url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    base = url.rsplit("/", 1)[0] if url.count("/") > 2 else url
    return f"{base}/15"


def _configure_environment() -> None:
    os.environ["REDIS_URL"] = _test_redis_url()
    url = _test_database_url()
    asyncio.run(_ensure_database(url))
    os.environ["DATABASE_URL"] = url
    os.environ.setdefault("APP_DB_PASSWORD", "app_dev_password")


# Run at IMPORT time, not only in pytest_configure. pytest imports the conftest files of the paths named
# on the command line *before* calling pytest_configure, so `pytest tests/integration/test_x.py` used to
# import app.db.session (which caches the settings and builds the engines) while DATABASE_URL still
# pointed at the development database, and the tests ran there. This parent conftest is always imported
# before any child conftest or test module, so configuring here is early enough in every case.
_configure_environment()


def pytest_configure(config) -> None:
    _configure_environment()


def _assert_pointing_at_test_services() -> None:
    from app.config import get_settings

    settings = get_settings()
    database = make_url(settings.admin_database_url).database or ""
    redis_db = settings.redis_url.rsplit("/", 1)[-1]
    if not database.endswith("_test") or redis_db != "15":
        pytest.exit(
            f"Refusing to run: the app is configured for database {database!r} and Redis db {redis_db!r}, "
            "not the test ones. Tests delete data, so they must never see a development database.",
            returncode=2,
        )
    import sys

    if "app.db.session" in sys.modules:
        from app.db.session import admin_engine, app_engine

        for engine in (admin_engine, app_engine):
            if not (engine.url.database or "").endswith("_test"):
                pytest.exit(f"Refusing to run: an engine is bound to {engine.url.database!r}.", returncode=2)


@pytest.fixture(scope="session", autouse=True)
def _guard_against_non_test_databases() -> None:
    _assert_pointing_at_test_services()
