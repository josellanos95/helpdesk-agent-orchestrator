from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

# Name of the least-privilege Postgres role the app connects as at runtime.
# It is created/updated by the Alembic migrations using the admin connection
# below, and deliberately has neither SUPERUSER nor BYPASSRLS — see
# docs/adr/0001-multi-tenant-isolation-via-rls.md for why that matters.
APP_DB_ROLE = "app_runtime"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: str = "development"

    # Admin/owner connection (e.g. Railway's auto-injected DATABASE_URL, or the
    # postgres superuser locally/in CI). Used ONLY for migrations and seeding —
    # never for request-time queries, because it bypasses Row Level Security.
    admin_database_url: str = Field(
        default="postgresql+asyncpg://helpdesk:helpdesk@localhost:5432/helpdesk",
        validation_alias="DATABASE_URL",
    )

    @field_validator("admin_database_url")
    @classmethod
    def _force_asyncpg_driver(cls, v: str) -> str:
        """Railway (and Heroku-style envs) hand out DATABASE_URL as a plain
        postgres:// or postgresql:// string. Without a driver suffix,
        SQLAlchemy defaults to the sync psycopg2 driver — which isn't even
        installed here — instead of asyncpg. Force it explicitly."""
        if v.startswith("postgres://"):
            v = "postgresql://" + v[len("postgres://") :]
        if v.startswith("postgresql://"):
            v = "postgresql+asyncpg://" + v[len("postgresql://") :]
        return v
    # Password for the app_runtime role. Same value must be used when the
    # migration creates/updates the role (see migrations) and here to build
    # the runtime connection string.
    app_db_password: str = "app_dev_password"

    redis_url: str = "redis://localhost:6379/0"
    openai_api_key: str | None = None
    openai_model: str = "gpt-5-mini"
    agent_max_steps: int = 6
    cors_origins: list[str] = ["http://localhost:5173"]

    @property
    def app_database_url(self) -> str:
        """Connection string for the restricted app_runtime role (RLS-enforced)."""
        url = make_url(self.admin_database_url)
        url = url.set(username=APP_DB_ROLE, password=self.app_db_password)
        # str(url) masks the password as '***' (SQLAlchemy's default safety
        # behavior) — that's the right default for logging, but useless for a
        # connection string a driver actually has to authenticate with.
        return url.render_as_string(hide_password=False)


@lru_cache
def get_settings() -> Settings:
    return Settings()
