import uuid
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.config import Settings
from app.services import limits
from app.services.limits import Who

pytestmark = pytest.mark.integration


def settings(**kwargs) -> Settings:
    return Settings(_env_file=None, **kwargs)


def who(session_id: str | None = "s1", ip: str = "1.2.3.4") -> Who:
    return Who(tenant_id=uuid.uuid4(), ip=ip, session_id=session_id)


async def test_a_full_window_answers_429_with_a_retry_after(redis_client):
    for _ in range(3):
        await limits.hit(redis_client, "rl:test", 3, 60)
    with pytest.raises(HTTPException) as caught:
        await limits.hit(redis_client, "rl:test", 3, 60)
    assert caught.value.status_code == 429
    assert caught.value.detail["code"] == "rate_limited"
    assert 1 <= int(caught.value.headers["Retry-After"]) <= 60


async def test_a_limit_of_zero_is_off(redis_client):
    for _ in range(50):
        await limits.hit(redis_client, "rl:off", 0, 60)


async def test_windows_are_per_key(redis_client):
    await limits.hit(redis_client, "rl:a", 1, 60)
    await limits.hit(redis_client, "rl:b", 1, 60)


async def test_spend_is_counted_per_session_ip_and_day(redis_client):
    s = settings(session_budget_usd=1, ip_daily_budget_usd=2, daily_budget_usd=3)
    me = who()
    await limits.record_spend(redis_client, me, Decimal("0.25"))
    await limits.record_spend(redis_client, me, Decimal("0.10"))
    state = await limits.budget(redis_client, s, me)
    assert state.spent_usd == {"day": Decimal("0.35"), "ip": Decimal("0.35"), "session": Decimal("0.35")}
    assert state.remaining("session") == Decimal("0.65")
    assert state.remaining("day") == Decimal("2.65")


async def test_another_session_on_the_same_ip_shares_the_ip_and_day_but_not_the_session(redis_client):
    s = settings(session_budget_usd=1)
    await limits.record_spend(redis_client, who("s1"), Decimal("0.4"))
    state = await limits.budget(redis_client, s, who("s2"))
    assert state.spent_usd["session"] == 0
    assert state.spent_usd["ip"] == Decimal("0.4")


@pytest.mark.parametrize(
    "cap, code",
    [
        ({"session_budget_usd": 0.5}, "budget_exhausted_session"),
        ({"ip_daily_budget_usd": 0.5}, "budget_exhausted_ip"),
        ({"daily_budget_usd": 0.5}, "budget_exhausted_day"),
    ],
)
async def test_each_cap_stops_new_work_with_its_own_code(redis_client, cap, code):
    me = who()
    base = {"session_budget_usd": 0, "ip_daily_budget_usd": 0, "daily_budget_usd": 0} | cap
    s = settings(**base)
    await limits.ensure_budget(redis_client, s, me)  # nothing spent yet
    await limits.record_spend(redis_client, me, Decimal("0.5"))
    with pytest.raises(HTTPException) as caught:
        await limits.ensure_budget(redis_client, s, me)
    assert caught.value.status_code == 429
    assert caught.value.detail["code"] == code


async def test_a_cap_of_zero_never_blocks(redis_client):
    s = settings(session_budget_usd=0, ip_daily_budget_usd=0, daily_budget_usd=0)
    me = who()
    await limits.record_spend(redis_client, me, Decimal("999"))
    await limits.ensure_budget(redis_client, s, me)
    assert (await limits.budget(redis_client, s, me)).remaining("session") is None


async def test_without_a_session_only_ip_and_day_are_counted(redis_client):
    anonymous = who(session_id=None)
    await limits.record_spend(redis_client, anonymous, Decimal("0.1"))
    state = await limits.budget(redis_client, settings(), anonymous)
    assert set(state.spent_usd) == {"day", "ip"}


async def test_tiny_costs_do_not_vanish_to_rounding(redis_client):
    me = who()
    for _ in range(1000):
        await limits.record_spend(redis_client, me, Decimal("0.000065"))
    state = await limits.budget(redis_client, settings(), me)
    assert state.spent_usd["session"] == Decimal("0.065")
