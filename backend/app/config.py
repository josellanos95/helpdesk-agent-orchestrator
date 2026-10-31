import secrets
from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

# Name of the least-privilege Postgres role the app connects as at runtime.
# It is created/updated by the Alembic migrations using the admin connection
# below, and deliberately has neither SUPERUSER nor BYPASSRLS — see
# docs/adr/0001-multi-tenant-isolation-via-rls.md for why that matters.
APP_DB_ROLE = "app_runtime"
# Published in this repo, so production refuses it.
DEV_APP_DB_PASSWORD = "app_dev_password"


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
    app_db_password: str = DEV_APP_DB_PASSWORD

    redis_url: str = "redis://localhost:6379/0"
    openai_api_key: str | None = None
    openai_model: str = "gpt-5-mini"
    # How hard a reasoning model thinks before answering. "low" halves latency and cost with the same pass
    # rate on the evals (docs/evals.md). Empty (OPENAI_REASONING_EFFORT=) sends nothing: needed for models
    # that do not reason, which reject the parameter.
    openai_reasoning_effort: Literal["minimal", "low", "medium", "high"] | None = "low"

    @field_validator("openai_reasoning_effort", mode="before")
    @classmethod
    def _blank_effort_means_model_default(cls, value: object) -> object:
        return value or None

    # Any OpenAI-compatible endpoint (DeepSeek, Kimi, OpenRouter, a local server...). None = OpenAI.
    openai_base_url: str | None = None
    # Embeddings are configured apart from chat: not every chat provider offers them. The vector
    # column is 1536-wide, so the model must produce 1536 dims (text-embedding-3-small does).
    embedding_provider: Literal["openai", "hashing"] = "openai"
    embedding_model: str = "text-embedding-3-small"
    embedding_api_key: str | None = None  # falls back to openai_api_key
    embedding_base_url: str | None = None  # None = OpenAI (NOT openai_base_url)
    # Below this cosine similarity (and with no keyword match) a passage is treated as unrelated.
    kb_min_similarity: float = 0.3
    agent_max_steps: int = 6
    # Per-conversation lock; renewed before every model call, so it only has to outlive one step.
    conversation_lock_ttl_seconds: int = 120
    cors_origins: list[str] = ["http://localhost:5173"]

    # --- Public demo protection (M8a, ADR 0007) -------------------------------------------------------
    # "header": the tenant comes from X-Tenant-Id and nobody is authenticated (local development and the
    # test suite). "signed": every request needs a Bearer token minted by POST /api/demo/session; tenant
    # and employee come from the token. A valid token is honoured in both modes.
    auth_mode: Literal["header", "signed"] = "header"
    demo_token_secret: str | None = None
    demo_token_ttl_hours: int = 12
    # Behind a reverse proxy (Caddy) the client address is the first X-Forwarded-For hop. Only enable this
    # when such a proxy is really in front, otherwise any caller could choose its own "IP".
    trust_forwarded_for: bool = False

    # Spend caps in USD (chat, tool and embedding costs). 0 disables a cap.
    daily_budget_usd: float = 1.00
    ip_daily_budget_usd: float = 0.25
    session_budget_usd: float = 0.10

    # Fixed-window rate limits (requests per window). 0 disables a limit.
    messages_per_minute_session: int = 8
    messages_per_minute_ip: int = 20
    searches_per_minute_session: int = 20
    writes_per_minute_session: int = 10
    sessions_per_hour_ip: int = 30

    # Background sweep: stuck runs, expired approvals, old idempotency keys.
    maintenance_enabled: bool = True
    maintenance_interval_seconds: int = 60
    # A run still going after this long belonged to a process that died (bounded by lock TTL and timeouts).
    stuck_run_seconds: int = 600
    idempotency_ttl_hours: int = 24

    @model_validator(mode="after")
    def _production_must_authenticate(self) -> "Settings":
        if self.auth_mode == "signed" and not self.demo_token_secret:
            raise ValueError("AUTH_MODE=signed needs DEMO_TOKEN_SECRET")
        if not self.demo_token_secret:
            # Development: sessions still work, with a secret that lives only as long as this process.
            self.demo_token_secret = secrets.token_hex(32)
        if self.environment == "production":
            if self.auth_mode != "signed":
                raise ValueError("AUTH_MODE must be 'signed' when ENVIRONMENT=production")
            if not self.demo_token_secret or len(self.demo_token_secret) < 32:
                raise ValueError("DEMO_TOKEN_SECRET must be at least 32 characters in production")
            if self.app_db_password == DEV_APP_DB_PASSWORD:
                raise ValueError("APP_DB_PASSWORD must be set in production (the default is public)")
        return self

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
