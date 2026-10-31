import pytest
from sqlalchemy.engine import make_url

from app.config import APP_DB_ROLE, Settings


def make_settings(url: str, password: str = "s3cret") -> Settings:
    return Settings(DATABASE_URL=url, app_db_password=password, _env_file=None)


@pytest.mark.parametrize("scheme", ["postgres", "postgresql", "postgresql+asyncpg"])
def test_database_url_always_uses_the_asyncpg_driver(scheme):
    """Railway hands out plain postgres:// URLs; without the driver suffix
    SQLAlchemy would pick psycopg2, which is not installed."""
    settings = make_settings(f"{scheme}://u:p@host:5432/db")
    assert make_url(settings.admin_database_url).drivername == "postgresql+asyncpg"


def test_runtime_url_uses_the_restricted_role_and_the_real_password():
    """Regression for ADR 0001 bug 1: str(URL) masks the password as '***'."""
    runtime = make_url(make_settings("postgresql+asyncpg://admin:adminpw@host:5432/db").app_database_url)
    assert runtime.username == APP_DB_ROLE
    assert runtime.password == "s3cret"
    assert (runtime.host, runtime.port, runtime.database) == ("host", 5432, "db")


def test_runtime_url_never_reuses_the_admin_credentials():
    settings = make_settings("postgresql+asyncpg://admin:adminpw@host:5432/db")
    assert "adminpw" not in settings.app_database_url
    assert "admin:" not in settings.app_database_url
