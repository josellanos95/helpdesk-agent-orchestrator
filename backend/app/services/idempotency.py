"""Request-level idempotency (the `Idempotency-Key` header on POST .../messages).

A client that times out and resends the same message must not run the agent twice. Semantics follow
the usual convention:
- first request with a key: claimed, runs normally, its response is stored
- same key + same body again: the stored response is replayed, nothing runs
- same key + different body: rejected (422), it is a client bug
- same key while the first is still running: rejected (409), retry shortly
- the first request failed: the key is released so the client can retry for real
"""

import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import IdempotencyKey

IN_PROGRESS = "in_progress"
COMPLETED = "completed"
# A claim still in progress after this long belongs to a process that died (a run is bounded by the
# conversation lock TTL and the model timeouts), so a retry may take it over instead of getting 409 forever.
STALE_AFTER_SECONDS = 300


@dataclass(frozen=True)
class Claim:
    outcome: Literal["claimed", "replay", "mismatch", "in_progress"]
    response: dict | None = None


def request_hash(conversation_id: uuid.UUID, content: str) -> str:
    payload = json.dumps({"conversation_id": str(conversation_id), "content": content}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


async def claim(session: AsyncSession, tenant_id: uuid.UUID, key: str, req_hash: str) -> Claim:
    inserted = await session.scalar(
        pg_insert(IdempotencyKey)
        .values(tenant_id=tenant_id, key=key, request_hash=req_hash, status=IN_PROGRESS)
        .on_conflict_do_nothing(index_elements=["tenant_id", "key"])
        .returning(IdempotencyKey.id)
    )
    if inserted is not None:
        return Claim("claimed")
    row = await session.scalar(select(IdempotencyKey).where(IdempotencyKey.key == key))
    if row.request_hash != req_hash:
        return Claim("mismatch")
    if row.status == COMPLETED:
        return Claim("replay", row.response)
    # Compare-and-set, so two retries racing for an abandoned claim cannot both win it.
    took_over = await session.scalar(
        update(IdempotencyKey)
        .where(
            IdempotencyKey.id == row.id,
            IdempotencyKey.status == IN_PROGRESS,
            IdempotencyKey.created_at < func.now() - text(f"interval '{STALE_AFTER_SECONDS} seconds'"),
        )
        .values(created_at=func.now())
        .returning(IdempotencyKey.id)
    )
    return Claim("claimed") if took_over else Claim("in_progress")


async def complete(session: AsyncSession, key: str, response: dict) -> None:
    await session.execute(
        update(IdempotencyKey)
        .where(IdempotencyKey.key == key)
        .values(status=COMPLETED, response=response)
    )


async def release(session: AsyncSession, key: str) -> None:
    """Drop an unfinished claim so the client can retry. Completed keys are never released."""
    await session.execute(
        delete(IdempotencyKey).where(IdempotencyKey.key == key, IdempotencyKey.status == IN_PROGRESS)
    )
