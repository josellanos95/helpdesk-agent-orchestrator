"""One agent run at a time per conversation.

Two runs on the same conversation would read the same history, both call the model and write
interleaved messages (and, before the tool ledger, could both open the same ticket). A Redis lock
serialises them across API processes; the second caller is told to retry (HTTP 409).

Safety properties, each covered by a test:
- acquired atomically (SET NX PX), so only one holder
- released only by its owner (token compared in a Lua script), so a slow run whose lock already
  expired cannot delete the lock of the run that took over
- short TTL, renewed before every model call, so a crashed process frees the conversation by itself
- renewal fails loudly if the lock was lost, and the run stops instead of racing the new owner
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass

from redis.asyncio import Redis
from redis.exceptions import RedisError

_RELEASE = "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end"
_RENEW = (
    "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('pexpire', KEYS[1], ARGV[2]) "
    "else return 0 end"
)


class ConversationBusy(Exception):
    """Another run is already working on this conversation."""


class LockLost(Exception):
    """The lock expired or was taken over while the run was still going."""


def lock_key(tenant_id: uuid.UUID, conversation_id: uuid.UUID) -> str:
    return f"triagent:lock:{tenant_id}:{conversation_id}"


@dataclass
class ConversationLock:
    redis: Redis
    key: str
    token: str
    ttl_ms: int

    async def renew(self) -> None:
        if not await self.redis.eval(_RENEW, 1, self.key, self.token, self.ttl_ms):
            raise LockLost(f"lost the lock on {self.key}")


@asynccontextmanager
async def conversation_lock(
    redis: Redis, tenant_id: uuid.UUID, conversation_id: uuid.UUID, *, ttl_seconds: int
) -> AsyncIterator[ConversationLock]:
    lock = ConversationLock(
        redis=redis,
        key=lock_key(tenant_id, conversation_id),
        token=uuid.uuid4().hex,
        ttl_ms=ttl_seconds * 1000,
    )
    if not await redis.set(lock.key, lock.token, nx=True, px=lock.ttl_ms):
        raise ConversationBusy(lock.key)
    try:
        yield lock
    finally:
        # Best effort: if Redis is down here the TTL still frees the conversation.
        with suppress(RedisError):
            await redis.eval(_RELEASE, 1, lock.key, lock.token)
