"""Idempotency claims at the service level (the HTTP behaviour is in test_api_conversations)."""

import asyncio
import uuid

import pytest
from sqlalchemy import text

from app.db.session import AdminSessionLocal
from app.services import idempotency

pytestmark = pytest.mark.integration


async def claim(as_tenant, tenant_id, key, req_hash="h"):
    async with as_tenant(tenant_id) as session:
        return await idempotency.claim(session, tenant_id, key, req_hash)


async def age(key: str, seconds: int) -> None:
    async with AdminSessionLocal() as session:
        await session.execute(
            text("UPDATE idempotency_keys SET created_at = now() - make_interval(secs => :s) WHERE key = :k"),
            {"s": seconds, "k": key},
        )
        await session.commit()


async def test_a_fresh_in_progress_claim_is_not_stolen(two_tenants, as_tenant):
    tenant = two_tenants.a.id
    key = f"k-{uuid.uuid4().hex}"
    assert (await claim(as_tenant, tenant, key)).outcome == "claimed"
    assert (await claim(as_tenant, tenant, key)).outcome == "in_progress"


async def test_a_claim_abandoned_by_a_dead_process_can_be_taken_over(two_tenants, as_tenant):
    tenant = two_tenants.a.id
    key = f"k-{uuid.uuid4().hex}"
    await claim(as_tenant, tenant, key)
    await age(key, idempotency.STALE_AFTER_SECONDS + 5)

    assert (await claim(as_tenant, tenant, key)).outcome == "claimed"
    # ...and the takeover refreshed it, so the next retry sees it as in progress again.
    assert (await claim(as_tenant, tenant, key)).outcome == "in_progress"


async def test_only_one_of_several_racing_retries_wins_an_abandoned_claim(two_tenants, as_tenant):
    tenant = two_tenants.a.id
    key = f"k-{uuid.uuid4().hex}"
    await claim(as_tenant, tenant, key)
    await age(key, idempotency.STALE_AFTER_SECONDS + 5)

    outcomes = await asyncio.gather(*[claim(as_tenant, tenant, key) for _ in range(6)])
    assert sorted(o.outcome for o in outcomes) == ["claimed"] + ["in_progress"] * 5


async def test_a_completed_key_is_never_taken_over_however_old(two_tenants, as_tenant):
    tenant = two_tenants.a.id
    key = f"k-{uuid.uuid4().hex}"
    await claim(as_tenant, tenant, key)
    async with as_tenant(tenant) as session:
        await idempotency.complete(session, key, {"reply": "stored"})
    await age(key, idempotency.STALE_AFTER_SECONDS * 100)

    again = await claim(as_tenant, tenant, key)
    assert (again.outcome, again.response) == ("replay", {"reply": "stored"})


async def test_release_only_drops_unfinished_claims(two_tenants, as_tenant):
    tenant = two_tenants.a.id
    pending, done = f"k-{uuid.uuid4().hex}", f"k-{uuid.uuid4().hex}"
    await claim(as_tenant, tenant, pending)
    await claim(as_tenant, tenant, done)
    async with as_tenant(tenant) as session:
        await idempotency.complete(session, done, {"reply": "x"})
        await idempotency.release(session, pending)
        await idempotency.release(session, done)

    assert (await claim(as_tenant, tenant, pending)).outcome == "claimed"  # was released
    assert (await claim(as_tenant, tenant, done)).outcome == "replay"  # was not
