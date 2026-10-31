"""Rate limits and spend caps, kept in Redis.

Rate limits are fixed windows (INCR + EXPIRE): cheap and good enough to stop a script from hammering the
model. Spend is counted in micro-dollars (integers, so no float drift) in three scopes: the whole demo per
day, one IP per day and one session. A cap that is reached answers 429 with a machine-readable code so the
UI can say what happened; every cap can be switched off with 0.

Spend is checked *before* a run and recorded *after* it, so one run can overshoot a cap by its own cost
(a few tenths of a cent). That is the price of not holding a lock across a model call.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from fastapi import HTTPException
from redis.asyncio import Redis

from app.config import Settings

MICRO = 1_000_000
SESSION_KEY_TTL_SECONDS = 3 * 24 * 3600
DAY_KEY_TTL_SECONDS = 2 * 24 * 3600


def limit_error(code: str, message: str, retry_after: int | None = None) -> HTTPException:
    headers = {"Retry-After": str(max(1, retry_after))} if retry_after else None
    return HTTPException(status_code=429, detail={"code": code, "message": message}, headers=headers)


async def hit(redis: Redis, key: str, limit: int, window_seconds: int) -> None:
    """Count one request in a fixed window; raise 429 `rate_limited` when the window is full."""
    if limit <= 0:
        return
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, window_seconds)
    if count > limit:
        ttl = await redis.ttl(key)
        raise limit_error(
            "rate_limited",
            "Too many requests. Wait a moment and try again.",
            ttl if ttl and ttl > 0 else window_seconds,
        )


@dataclass(frozen=True)
class Who:
    """What spend and rate limits are counted against."""

    tenant_id: uuid.UUID
    ip: str
    session_id: str | None  # None when nobody signed in (header mode)


def _today() -> str:
    return datetime.now(UTC).strftime("%Y%m%d")


def _micro(usd: Decimal | float) -> int:
    return int(Decimal(str(usd)) * MICRO)


def _keys(who: Who) -> dict[str, str]:
    keys = {"day": f"spend:day:{_today()}", "ip": f"spend:ip:{who.ip}:{_today()}"}
    if who.session_id:
        keys["session"] = f"spend:session:{who.session_id}"
    return keys


def _caps(settings: Settings) -> dict[str, int]:
    return {
        "day": _micro(settings.daily_budget_usd),
        "ip": _micro(settings.ip_daily_budget_usd),
        "session": _micro(settings.session_budget_usd),
    }


@dataclass(frozen=True)
class Budget:
    spent_usd: dict[str, Decimal]
    cap_usd: dict[str, Decimal]

    def remaining(self, scope: str) -> Decimal | None:
        cap = self.cap_usd.get(scope)
        if cap is None or cap <= 0:
            return None
        return max(Decimal(0), cap - self.spent_usd.get(scope, Decimal(0)))


async def budget(redis: Redis, settings: Settings, who: Who) -> Budget:
    keys = _keys(who)
    values = await redis.mget(list(keys.values()))
    caps = _caps(settings)
    return Budget(
        spent_usd={scope: Decimal(int(v or 0)) / MICRO for scope, v in zip(keys, values, strict=True)},
        cap_usd={scope: Decimal(caps[scope]) / MICRO for scope in keys},
    )


async def ensure_budget(redis: Redis, settings: Settings, who: Who) -> None:
    """Refuse to start work once any cap is spent."""
    state = await budget(redis, settings, who)
    messages = {
        "day": "The demo's budget for today is used up. It resets at midnight UTC.",
        "ip": "This connection has used its share of today's demo budget.",
        "session": "This session has used its demo budget. Choose a person again to start a fresh session.",
    }
    for scope, text in messages.items():
        remaining = state.remaining(scope)
        if remaining is not None and remaining <= 0:
            raise limit_error(f"budget_exhausted_{scope}", text)


async def record_spend(redis: Redis, who: Who, usd: Decimal | float) -> None:
    amount = _micro(usd)
    if amount <= 0:
        return
    for scope, key in _keys(who).items():
        await redis.incrby(key, amount)
        await redis.expire(key, SESSION_KEY_TTL_SECONDS if scope == "session" else DAY_KEY_TTL_SECONDS)
