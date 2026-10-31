import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.db.models import (
    AgentRun,
    AgentRunStatus,
    Approval,
    ApprovalStatus,
    AuditLog,
    IdempotencyKey,
    Message,
)
from app.db.session import AdminSessionLocal
from app.services import maintenance

pytestmark = pytest.mark.integration


def naive_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


async def seed(tenant) -> dict[str, uuid.UUID]:
    """A stuck run, a live run, an unsigned expired approval, a live approval, an old and a young key."""
    now = naive_now()
    ids: dict[str, uuid.UUID] = {}
    async with AdminSessionLocal() as session:
        for name, age in (("stuck", timedelta(hours=2)), ("live", timedelta(seconds=30))):
            run = AgentRun(
                tenant_id=tenant.id,
                conversation_id=tenant.conversation_id,
                model="m",
                status=AgentRunStatus.running,
                started_at=now - age,
            )
            session.add(run)
            await session.flush()
            ids[name] = run.id
        for name, expires in (("lapsed", now - timedelta(minutes=5)), ("open", now + timedelta(hours=1))):
            approval = Approval(
                tenant_id=tenant.id,
                conversation_id=tenant.conversation_id,
                requested_by=tenant.employee_id,
                tool_call_id=f"call-{name}-{uuid.uuid4().hex[:6]}",
                tool_name="reset_password",
                arguments="{}",
                status=ApprovalStatus.pending,
                expires_at=expires,
            )
            session.add(approval)
            await session.flush()
            ids[name] = approval.id
        for name, age in (("old_key", timedelta(hours=48)), ("young_key", timedelta(hours=1))):
            key = IdempotencyKey(
                tenant_id=tenant.id,
                key=f"{name}-{uuid.uuid4().hex[:6]}",
                request_hash="h",
                status="completed",
                created_at=now - age,
            )
            session.add(key)
            await session.flush()
            ids[name] = key.id
        await session.commit()
    return ids


async def sweep():
    return await maintenance.sweep(stuck_run_seconds=600, idempotency_ttl_hours=24)


async def test_a_stuck_run_is_closed_and_a_live_one_is_left_alone(two_tenants):
    ids = await seed(two_tenants.a)
    report = await sweep()
    assert report.runs_closed >= 1
    async with AdminSessionLocal() as session:
        stuck = await session.get(AgentRun, ids["stuck"])
        live = await session.get(AgentRun, ids["live"])
    assert stuck.status == AgentRunStatus.failed
    assert stuck.error == maintenance.STUCK_RUN_ERROR
    assert stuck.finished_at is not None
    assert live.status == AgentRunStatus.running and live.finished_at is None


async def test_an_unsigned_approval_expires_and_the_employee_is_told(two_tenants):
    ids = await seed(two_tenants.a)
    await sweep()
    async with AdminSessionLocal() as session:
        lapsed = await session.get(Approval, ids["lapsed"])
        still_open = await session.get(Approval, ids["open"])
        told = (
            await session.scalars(
                select(Message).where(
                    Message.conversation_id == two_tenants.a.conversation_id,
                    Message.content.like("Update: your request%expired%"),
                )
            )
        ).all()
        audited = (
            await session.scalars(
                select(AuditLog).where(
                    AuditLog.action == "approval.expired", AuditLog.subject == str(ids["lapsed"])
                )
            )
        ).all()
    assert lapsed.status == ApprovalStatus.expired and lapsed.decided_at is not None
    assert still_open.status == ApprovalStatus.pending
    assert len(told) == 1
    assert len(audited) == 1 and audited[0].actor_type == "system"


async def test_old_idempotency_keys_go_and_young_ones_stay(two_tenants):
    ids = await seed(two_tenants.a)
    report = await sweep()
    assert report.keys_deleted >= 1
    async with AdminSessionLocal() as session:
        assert await session.get(IdempotencyKey, ids["old_key"]) is None
        assert await session.get(IdempotencyKey, ids["young_key"]) is not None


async def test_sweeping_twice_does_not_repeat_the_work(two_tenants):
    ids = await seed(two_tenants.a)
    await sweep()
    second = await sweep()
    assert second.runs_closed == 0 and second.approvals_expired == 0
    async with AdminSessionLocal() as session:
        told = (
            await session.scalars(
                select(Message).where(
                    Message.conversation_id == two_tenants.a.conversation_id,
                    Message.content.like("Update: your request%expired%"),
                )
            )
        ).all()
    assert len(told) == 1, ids


async def test_the_sweep_reaches_every_tenant(two_tenants):
    a = await seed(two_tenants.a)
    b = await seed(two_tenants.b)
    await sweep()
    async with AdminSessionLocal() as session:
        assert (await session.get(Approval, a["lapsed"])).status == ApprovalStatus.expired
        assert (await session.get(Approval, b["lapsed"])).status == ApprovalStatus.expired
