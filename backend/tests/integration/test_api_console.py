import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import func, select, update

from app.api.deps import get_llm, get_redis
from app.db.models import Approval, AuditLog, Ticket
from app.db.session import AdminSessionLocal
from app.main import app
from app.services.locks import conversation_lock
from tests.fakes import ScriptedLLM, call, say

pytestmark = pytest.mark.integration

RESET = {"reason": "I forgot my password and cannot log in"}


def headers(tenant) -> dict[str, str]:
    return {"X-Tenant-Id": str(tenant.id)}


@pytest.fixture
async def client(redis_client):
    app.dependency_overrides[get_redis] = lambda: redis_client
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


async def ask_for_reset(client, tenant, employee_id=None) -> tuple[str, str]:
    """An employee chats, the agent asks for a reset. Returns (conversation_id, approval_id)."""
    llm = ScriptedLLM(call("reset_password", RESET), say("It is waiting for approval."))
    app.dependency_overrides[get_llm] = lambda: llm
    created = await client.post(
        "/api/conversations",
        json={"employee_id": str(employee_id or tenant.employee_id)},
        headers=headers(tenant),
    )
    conversation_id = created.json()["id"]
    sent = await client.post(
        f"/api/conversations/{conversation_id}/messages",
        json={"content": "I forgot my password"},
        headers=headers(tenant),
    )
    assert sent.status_code == 200, sent.text
    pending = await client.get("/api/approvals", headers=headers(tenant))
    [mine] = [a for a in pending.json() if a["conversation_id"] == conversation_id]
    return conversation_id, mine["id"]


def decision(client, tenant, approval_id, approver_id, verb="approve", note=None):
    return client.post(
        f"/api/approvals/{approval_id}/decision",
        json={"decision": verb, "approver_id": str(approver_id), "note": note},
        headers=headers(tenant),
    )


async def count_audit(tenant, action) -> int:
    async with AdminSessionLocal() as session:
        return await session.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.tenant_id == tenant.id, AuditLog.action == action)
        )


# ---------------------------------------------------------------------------- approvals


async def test_full_flow_ask_list_decide_and_the_employee_is_told(client, two_tenants, support_agents):
    a = two_tenants.a
    conversation_id, approval_id = await ask_for_reset(client, a)

    pending = (await client.get("/api/approvals", headers=headers(a))).json()
    [item] = [p for p in pending if p["id"] == approval_id]
    assert item["status"] == "pending" and item["tool_name"] == "reset_password"
    assert item["requested_by_name"] == "Emp a" and item["arguments"] == RESET

    done = await decision(client, a, approval_id, support_agents["a"], note="verified by phone")
    assert done.status_code == 200
    assert done.json()["outcome"] == "approved" and done.json()["replayed"] is False
    assert done.json()["result"]["status"] == "reset_link_sent"

    history = await client.get(f"/api/conversations/{conversation_id}/messages", headers=headers(a))
    assert "approved your request and it has been carried out" in history.json()[-1]["content"]
    assert approval_id not in [
        p["id"] for p in (await client.get("/api/approvals", headers=headers(a))).json()
    ]
    approved = (await client.get("/api/approvals?status=approved", headers=headers(a))).json()
    assert approval_id in [p["id"] for p in approved]
    shown = await client.get(f"/api/approvals/{approval_id}", headers=headers(a))
    assert shown.json()["decision_note"] == "verified by phone"


async def test_the_decision_rules_hold_over_http(client, two_tenants, support_agents):
    a, b = two_tenants.a, two_tenants.b
    _, approval_id = await ask_for_reset(client, a)

    ordinary = await decision(client, a, approval_id, a.employee_id)
    other_tenants_agent = await decision(client, a, approval_id, support_agents["b"])
    unknown_approval = await decision(client, a, uuid.uuid4(), support_agents["a"])
    from_other_tenant = await decision(client, b, approval_id, support_agents["b"])
    bad_verb = await client.post(
        f"/api/approvals/{approval_id}/decision",
        json={"decision": "maybe", "approver_id": str(support_agents["a"])},
        headers=headers(a),
    )

    assert ordinary.status_code == 403
    assert other_tenants_agent.status_code == 403
    assert unknown_approval.status_code == 404
    assert from_other_tenant.status_code == 404
    assert bad_verb.status_code == 422
    assert await count_audit(a, "password_reset") == 0


async def test_a_support_agent_cannot_approve_their_own_request(client, two_tenants, support_agents):
    _, approval_id = await ask_for_reset(client, two_tenants.a, employee_id=support_agents["a"])
    response = await decision(client, two_tenants.a, approval_id, support_agents["a"])
    assert response.status_code == 403 and "own request" in response.json()["detail"]


async def test_one_tenant_never_lists_anothers_approvals(client, two_tenants, support_agents):
    _, approval_id = await ask_for_reset(client, two_tenants.a)
    seen_by_b = (await client.get("/api/approvals?status=all", headers=headers(two_tenants.b))).json()
    assert approval_id not in [p["id"] for p in seen_by_b]
    assert (
        await client.get(f"/api/approvals/{approval_id}", headers=headers(two_tenants.b))
    ).status_code == 404


async def test_a_double_click_executes_once_and_a_retry_gets_the_replay(client, two_tenants, support_agents):
    a = two_tenants.a
    _, approval_id = await ask_for_reset(client, a)

    responses = await asyncio.gather(
        *[decision(client, a, approval_id, support_agents["a"]) for _ in range(5)]
    )
    assert {r.status_code for r in responses} <= {200, 409}  # 409 = "conversation busy, retry"
    assert sum(r.status_code == 200 for r in responses) >= 1

    retry = await decision(client, a, approval_id, support_agents["a"])
    assert retry.status_code == 200 and retry.json()["outcome"] == "approved"
    assert await count_audit(a, "password_reset") == 1


async def test_deciding_waits_for_a_conversation_that_is_mid_run(
    client, two_tenants, support_agents, redis_client
):
    """The follow-up message must not land between a tool call and its result."""
    a = two_tenants.a
    conversation_id, approval_id = await ask_for_reset(client, a)

    async with conversation_lock(redis_client, a.id, uuid.UUID(conversation_id), ttl_seconds=30):
        busy = await decision(client, a, approval_id, support_agents["a"])
        assert busy.status_code == 409
        history = await client.get(f"/api/conversations/{conversation_id}/messages", headers=headers(a))
        assert "approved" not in history.json()[-1]["content"]  # nothing was appended
    assert await count_audit(a, "password_reset") == 0

    assert (await decision(client, a, approval_id, support_agents["a"])).status_code == 200


async def test_an_expired_request_is_a_409(client, two_tenants, support_agents):
    a = two_tenants.a
    _, approval_id = await ask_for_reset(client, a)
    async with AdminSessionLocal() as session:
        await session.execute(
            update(Approval)
            .where(Approval.id == uuid.UUID(approval_id))
            .values(expires_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=1))
        )
        await session.commit()

    response = await decision(client, a, approval_id, support_agents["a"])
    assert response.status_code == 409 and "expired" in response.json()["detail"]
    assert await count_audit(a, "password_reset") == 0


async def test_a_rejection_is_told_to_the_employee_with_the_reason(client, two_tenants, support_agents):
    a = two_tenants.a
    conversation_id, approval_id = await ask_for_reset(client, a)
    response = await decision(
        client, a, approval_id, support_agents["a"], "reject", "Use the self-service page"
    )

    assert response.json()["outcome"] == "rejected"
    history = await client.get(f"/api/conversations/{conversation_id}/messages", headers=headers(a))
    assert "did not approve your request: Use the self-service page" in history.json()[-1]["content"]
    assert await count_audit(a, "password_reset") == 0


# -------------------------------------------------------------------------- escalations


async def only_escalation(client, tenant) -> dict:
    """The two_tenants fixture gives each tenant exactly one open escalation."""
    [escalation] = (await client.get("/api/escalations", headers=headers(tenant))).json()
    return escalation


def move(client, tenant, escalation_id, verb, who):
    return client.post(
        f"/api/escalations/{escalation_id}/{verb}", json={"approver_id": str(who)}, headers=headers(tenant)
    )


async def ticket_status(ticket_id) -> str:
    async with AdminSessionLocal() as session:
        return (await session.scalar(select(Ticket).where(Ticket.id == ticket_id))).status.value


async def test_the_escalation_queue_lists_what_needs_a_human(client, two_tenants):
    escalation = await only_escalation(client, two_tenants.a)
    assert escalation["status"] == "pending" and escalation["ticket_subject"] == "Subject a"
    assert escalation["ticket_id"] == str(two_tenants.a.ticket_id)
    assert (await client.get("/api/escalations", headers=headers(two_tenants.b))).json()[0][
        "id"
    ] != escalation["id"]


async def test_working_an_escalation_from_pending_to_resolved(client, two_tenants, support_agents):
    a = two_tenants.a
    escalation = await only_escalation(client, a)

    ack = await move(client, a, escalation["id"], "acknowledge", support_agents["a"])
    assert ack.json()["status"] == "acknowledged" and await ticket_status(a.ticket_id) == "in_progress"
    assert (
        await move(client, a, escalation["id"], "acknowledge", support_agents["a"])
    ).status_code == 200  # idempotent

    resolved = await move(client, a, escalation["id"], "resolve", support_agents["a"])
    assert resolved.json()["status"] == "resolved" and resolved.json()["resolved_at"]
    assert await ticket_status(a.ticket_id) == "resolved"
    assert (
        await move(client, a, escalation["id"], "resolve", support_agents["a"])
    ).status_code == 200  # idempotent
    assert (await move(client, a, escalation["id"], "acknowledge", support_agents["a"])).status_code == 409

    assert (await client.get("/api/escalations", headers=headers(a))).json() == []  # "open" by default
    assert len((await client.get("/api/escalations?status=all", headers=headers(a))).json()) == 1
    assert (
        await count_audit(a, "escalation.acknowledged") == 1
        and await count_audit(a, "escalation.resolved") == 1
    )


async def test_only_support_agents_of_the_tenant_can_work_the_queue(client, two_tenants, support_agents):
    a, b = two_tenants.a, two_tenants.b
    escalation = await only_escalation(client, a)

    assert (await move(client, a, escalation["id"], "acknowledge", a.employee_id)).status_code == 403
    assert (await move(client, a, escalation["id"], "resolve", support_agents["b"])).status_code == 403
    assert (await move(client, b, escalation["id"], "resolve", support_agents["b"])).status_code == 404
    assert (await only_escalation(client, a))["status"] == "pending"


async def test_a_pending_escalation_can_be_resolved_directly(client, two_tenants, support_agents):
    escalation = await only_escalation(client, two_tenants.a)
    resolved = await move(client, two_tenants.a, escalation["id"], "resolve", support_agents["a"])
    assert resolved.json()["status"] == "resolved"
