import asyncio
import uuid

import pytest
from redis.exceptions import RedisError

from app.services.locks import ConversationBusy, LockLost, conversation_lock, lock_key

pytestmark = pytest.mark.integration

TENANT = uuid.uuid4()


async def test_only_one_holder_at_a_time(redis_client):
    conversation = uuid.uuid4()
    async with conversation_lock(redis_client, TENANT, conversation, ttl_seconds=30):
        with pytest.raises(ConversationBusy):
            async with conversation_lock(redis_client, TENANT, conversation, ttl_seconds=30):
                pytest.fail("second holder must not get in")


async def test_it_is_free_again_after_release_even_if_the_body_raised(redis_client):
    conversation = uuid.uuid4()
    with pytest.raises(RuntimeError):
        async with conversation_lock(redis_client, TENANT, conversation, ttl_seconds=30):
            raise RuntimeError("run crashed")
    assert await redis_client.exists(lock_key(TENANT, conversation)) == 0
    async with conversation_lock(redis_client, TENANT, conversation, ttl_seconds=30):
        pass


async def test_different_conversations_and_tenants_do_not_block_each_other(redis_client):
    conversation = uuid.uuid4()
    async with conversation_lock(redis_client, TENANT, conversation, ttl_seconds=30):
        async with conversation_lock(redis_client, TENANT, uuid.uuid4(), ttl_seconds=30):
            async with conversation_lock(redis_client, uuid.uuid4(), conversation, ttl_seconds=30):
                pass


async def test_concurrent_attempts_let_exactly_one_through(redis_client):
    conversation = uuid.uuid4()
    entered = []

    async def attempt(n):
        try:
            async with conversation_lock(redis_client, TENANT, conversation, ttl_seconds=30):
                entered.append(n)
                await asyncio.sleep(0.2)
        except ConversationBusy:
            return "busy"
        return "ran"

    results = await asyncio.gather(*[attempt(n) for n in range(10)])
    assert sorted(results) == ["busy"] * 9 + ["ran"]
    assert len(entered) == 1


async def test_renew_pushes_the_expiry_forward(redis_client):
    conversation = uuid.uuid4()
    async with conversation_lock(redis_client, TENANT, conversation, ttl_seconds=5) as lock:
        await asyncio.sleep(0.5)
        before = await redis_client.pttl(lock.key)
        await lock.renew()
        after = await redis_client.pttl(lock.key)
    assert before < 4600 < after <= 5000


async def test_renew_fails_loudly_once_the_lock_is_lost(redis_client):
    conversation = uuid.uuid4()
    async with conversation_lock(redis_client, TENANT, conversation, ttl_seconds=30) as lock:
        await redis_client.set(lock.key, "someone-else")
        with pytest.raises(LockLost):
            await lock.renew()
        await redis_client.delete(lock.key)
        with pytest.raises(LockLost):
            await lock.renew()


async def test_a_crashed_holder_frees_the_conversation_by_expiry(redis_client):
    conversation = uuid.uuid4()
    lock_cm = conversation_lock(redis_client, TENANT, conversation, ttl_seconds=1)
    await lock_cm.__aenter__()  # acquire and "crash": never release
    await asyncio.sleep(1.3)
    async with conversation_lock(redis_client, TENANT, conversation, ttl_seconds=30):
        pass


async def test_an_expired_holder_cannot_release_the_new_owners_lock(redis_client):
    conversation = uuid.uuid4()
    slow = conversation_lock(redis_client, TENANT, conversation, ttl_seconds=1)
    await slow.__aenter__()
    await asyncio.sleep(1.3)  # slow run's lock expired...
    async with conversation_lock(redis_client, TENANT, conversation, ttl_seconds=30) as new_owner:
        await slow.__aexit__(None, None, None)  # ...and now it "finishes" and releases
        assert await redis_client.get(new_owner.key) == new_owner.token  # the new owner is untouched


async def test_redis_being_down_is_an_error_not_a_free_pass():
    import redis.asyncio as redis

    dead = redis.Redis.from_url("redis://localhost:6399/0", decode_responses=True)
    with pytest.raises(RedisError):
        async with conversation_lock(dead, TENANT, uuid.uuid4(), ttl_seconds=30):
            pytest.fail("must not run without the lock")
    await dead.aclose()
