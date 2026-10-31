"""Housekeeping that nothing else would do (backlog 4, 5 and 23).

- A run still `running` long after any model call could be alive belonged to a process that died: close it
  as failed so a screen stops showing a live line forever.
- An approval nobody signed before it expired stays `pending` until someone happens to touch it: close it
  and tell the employee, in the conversation, that it expired.
- Idempotency keys are only useful for a retry shortly after the original: drop the old ones.

It sweeps every tenant, which the RLS-restricted runtime role cannot do, so it uses the admin session on
purpose (the same reason seeding does). Every write names its own tenant. A Redis lock makes it safe to run
from several processes: one sweep per interval wins.
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from redis.asyncio import Redis
from sqlalchemy import delete, select

from app.config import Settings
from app.db.models import (
    AgentRun,
    AgentRunStatus,
    Approval,
    ApprovalStatus,
    AuditLog,
    IdempotencyKey,
    Message,
    MessageRole,
)
from app.db.session import AdminSessionLocal

logger = logging.getLogger(__name__)

STUCK_RUN_ERROR = "Interrupted: the process stopped before this run finished."


@dataclass(frozen=True)
class SweepReport:
    runs_closed: int = 0
    approvals_expired: int = 0
    keys_deleted: int = 0


def _naive_utc(now: datetime | None) -> datetime:
    return (now or datetime.now(UTC)).replace(tzinfo=None)


async def sweep(
    *, stuck_run_seconds: int, idempotency_ttl_hours: int, now: datetime | None = None
) -> SweepReport:
    moment = _naive_utc(now)
    async with AdminSessionLocal() as session:
        async with session.begin():
            stuck = (
                await session.scalars(
                    select(AgentRun)
                    .where(
                        AgentRun.status == AgentRunStatus.running,
                        AgentRun.started_at < moment - timedelta(seconds=stuck_run_seconds),
                    )
                    .with_for_update(skip_locked=True)
                )
            ).all()
            for run in stuck:
                run.status = AgentRunStatus.failed
                run.error = STUCK_RUN_ERROR
                run.finished_at = moment

            lapsed = (
                await session.scalars(
                    select(Approval)
                    .where(Approval.status == ApprovalStatus.pending, Approval.expires_at < moment)
                    .with_for_update(skip_locked=True)
                )
            ).all()
            for approval in lapsed:
                approval.status = ApprovalStatus.expired
                approval.decided_at = moment
                what = approval.tool_name.replace("_", " ")
                session.add(
                    Message(
                        tenant_id=approval.tenant_id,
                        conversation_id=approval.conversation_id,
                        role=MessageRole.assistant,
                        content=f"Update: your request ({what}) was not signed in time and has expired. "
                        "Ask again if you still need it.",
                    )
                )
                session.add(
                    AuditLog(
                        tenant_id=approval.tenant_id,
                        actor_type="system",
                        action="approval.expired",
                        subject=str(approval.id),
                        details={"tool": approval.tool_name, "by": "maintenance"},
                    )
                )

            deleted = await session.execute(
                delete(IdempotencyKey).where(
                    IdempotencyKey.created_at < moment - timedelta(hours=idempotency_ttl_hours)
                )
            )
    return SweepReport(
        runs_closed=len(stuck), approvals_expired=len(lapsed), keys_deleted=deleted.rowcount or 0
    )


async def run_forever(redis: Redis, settings: Settings) -> None:
    """Sweep every `maintenance_interval_seconds`; never dies on an error, stops when cancelled."""
    interval = max(5, settings.maintenance_interval_seconds)
    while True:
        try:
            # SET NX EX: with several processes, only one of them sweeps in each interval.
            if await redis.set("maintenance:lock", "1", nx=True, ex=interval - 1):
                report = await sweep(
                    stuck_run_seconds=settings.stuck_run_seconds,
                    idempotency_ttl_hours=settings.idempotency_ttl_hours,
                )
                if any((report.runs_closed, report.approvals_expired, report.keys_deleted)):
                    logger.info("Maintenance sweep: %s", report)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Maintenance sweep failed; will try again next interval")
        await asyncio.sleep(interval)
