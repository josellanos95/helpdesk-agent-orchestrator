"""Test harness.

Tests never touch the development database. `pytest_configure` derives a
sibling database named `<dbname>_test` from DATABASE_URL, creates it if
missing, and points the app at it *before* any `app.*` module is imported
(engines are created at import time in app/db/session.py).
"""

import asyncio
import os

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


def pytest_configure(config) -> None:
    os.environ["REDIS_URL"] = _test_redis_url()
    url = _test_database_url()
    asyncio.run(_ensure_database(url))
    os.environ["DATABASE_URL"] = url
    os.environ.setdefault("APP_DB_PASSWORD", "app_dev_password")
