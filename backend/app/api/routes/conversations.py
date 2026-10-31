import logging
import uuid
from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from pydantic import BaseModel, Field
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.runner import run_agent
from app.agent.tools import ToolRegistry, default_registry
from app.api.deps import (
    Actor,
    Principal,
    actor_for,
    get_db,
    get_embedder,
    get_llm,
    get_principal,
    get_redis,
    get_tenant_id,
    get_who,
)
from app.config import get_settings
from app.db.models import (
    AgentRun,
    AgentRunStatus,
    AgentStep,
    Approval,
    ApprovalStatus,
    Conversation,
    Employee,
    Message,
    MessageRole,
)
from app.db.session import tenant_session
from app.llm.base import LLMClient
from app.llm.embeddings import Embedder
from app.services import idempotency, limits
from app.services.limits import Who
from app.services.locks import ConversationBusy, LockLost, conversation_lock

logger = logging.getLogger(__name__)
router = APIRouter()


class EmployeeOut(BaseModel):
    id: uuid.UUID
    full_name: str
    email: str
    job_title: str
    is_support_agent: bool

    model_config = {"from_attributes": True}


class ConversationCreate(BaseModel):
    employee_id: uuid.UUID


class ConversationOut(BaseModel):
    id: uuid.UUID
    employee_id: uuid.UUID

    model_config = {"from_attributes": True}


class MessageIn(BaseModel):
    content: str = Field(min_length=1, max_length=4000)


class ConversationListItem(BaseModel):
    id: uuid.UUID
    employee_id: uuid.UUID
    employee_name: str
    started_at: datetime
    last_message_at: datetime
    title: str
    preview: str
    pending_approvals: int


class MessageOut(BaseModel):
    id: uuid.UUID
    seq: int
    role: MessageRole
    content: str
    tool_name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list | None = None
    run_id: uuid.UUID | None = None
    step_index: int | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class RunSummary(BaseModel):
    run_id: uuid.UUID
    status: AgentRunStatus
    prompt_tokens: int
    completion_tokens: int
    cost_usd: Decimal


class ReplyOut(BaseModel):
    reply: str
    run: RunSummary


class StepOut(BaseModel):
    step_index: int
    kind: str
    name: str
    input: dict | list | None
    output: dict | list | None
    latency_ms: int
    prompt_tokens: int | None
    completion_tokens: int | None
    error: str | None

    model_config = {"from_attributes": True}


class RunOut(BaseModel):
    id: uuid.UUID
    conversation_id: uuid.UUID
    status: AgentRunStatus
    model: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: Decimal
    error: str | None
    started_at: datetime
    finished_at: datetime | None
    steps: list[StepOut]


def get_registry() -> ToolRegistry:
    return default_registry()


async def _conversation_or_404(
    session: AsyncSession, conversation_id: uuid.UUID, actor: Actor | None = None
) -> Conversation:
    # Another tenant's conversation is invisible under RLS, so it is indistinguishable from a missing one.
    # Another employee's conversation is hidden the same way (404, not 403: do not confirm it exists).
    conversation = await session.get(Conversation, conversation_id)
    if conversation is None or (
        actor is not None and not actor.may_see_all() and conversation.employee_id != actor.id
    ):
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


@router.get("/employees", response_model=list[EmployeeOut])
async def list_employees(session: AsyncSession = Depends(get_db)) -> list[Employee]:
    return list(await session.scalars(select(Employee).order_by(Employee.full_name)))


@router.get("/conversations", response_model=list[ConversationListItem])
async def list_conversations(
    employee_id: uuid.UUID | None = None,
    limit: int = Query(50, ge=1, le=100),
    session: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> list[ConversationListItem]:
    """Newest activity first. An employee passes their own id; support agents list the whole tenant."""
    actor = await actor_for(session, principal)
    if not actor.may_see_all():
        if employee_id not in (None, actor.id):
            raise HTTPException(status_code=403, detail="You can only list your own conversations.")
        employee_id = actor.id
    in_this_conversation = Message.conversation_id == Conversation.id
    last_at = (
        select(func.max(Message.created_at))
        .where(in_this_conversation)
        .correlate(Conversation)
        .scalar_subquery()
    )
    preview = (
        select(Message.content)
        .where(in_this_conversation, Message.role.in_([MessageRole.user, MessageRole.assistant]))
        .order_by(Message.seq.desc())
        .limit(1)
        .correlate(Conversation)
        .scalar_subquery()
    )
    title = (
        select(Message.content)
        .where(in_this_conversation, Message.role == MessageRole.user)
        .order_by(Message.seq)
        .limit(1)
        .correlate(Conversation)
        .scalar_subquery()
    )
    pending = (
        select(func.count())
        .select_from(Approval)
        .where(Approval.conversation_id == Conversation.id, Approval.status == ApprovalStatus.pending)
        .correlate(Conversation)
        .scalar_subquery()
    )
    query = (
        select(
            Conversation,
            Employee.full_name,
            last_at.label("last_at"),
            preview.label("preview"),
            title.label("title"),
            pending.label("pending"),
        )
        .join(Employee, Employee.id == Conversation.employee_id)
        .order_by(func.coalesce(last_at, Conversation.started_at).desc())
        .limit(limit)
    )
    if employee_id is not None:
        query = query.where(Conversation.employee_id == employee_id)
    return [
        ConversationListItem(
            id=c.id,
            employee_id=c.employee_id,
            employee_name=name,
            started_at=c.started_at,
            last_message_at=last or c.started_at,
            title=(first or "")[:120],
            preview=(text or "")[:160],
            pending_approvals=count,
        )
        for c, name, last, text, first, count in (await session.execute(query)).all()
    ]


@router.post("/conversations", response_model=ConversationOut, status_code=201)
async def create_conversation(
    body: ConversationCreate,
    session: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    principal: Principal = Depends(get_principal),
) -> Conversation:
    actor = await actor_for(session, principal)
    if actor.restricted and body.employee_id != actor.id:
        raise HTTPException(status_code=403, detail="You can only start conversations as yourself.")
    if await session.get(Employee, body.employee_id) is None:
        raise HTTPException(status_code=404, detail="Employee not found")
    conversation = Conversation(tenant_id=tenant_id, employee_id=body.employee_id)
    session.add(conversation)
    await session.flush()
    return conversation


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageOut])
async def list_messages(
    conversation_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> list[Message]:
    await _conversation_or_404(session, conversation_id, await actor_for(session, principal))
    rows = await session.scalars(
        select(Message).where(Message.conversation_id == conversation_id).order_by(Message.seq)
    )
    return list(rows)


@router.get("/conversations/{conversation_id}/runs", response_model=list[RunOut])
async def list_runs(
    conversation_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> list[RunOut]:
    """Every run of the conversation with its steps so far. Steps are committed one by one, so while a run is
    still going this is what lets a screen show the agent's work live."""
    await _conversation_or_404(session, conversation_id, await actor_for(session, principal))
    runs = (
        await session.scalars(
            select(AgentRun).where(AgentRun.conversation_id == conversation_id).order_by(AgentRun.started_at)
        )
    ).all()
    steps = (
        await session.scalars(
            select(AgentStep)
            .where(AgentStep.run_id.in_([r.id for r in runs]))
            .order_by(AgentStep.run_id, AgentStep.step_index)
        )
    ).all()
    by_run: dict[uuid.UUID, list[AgentStep]] = {}
    for step in steps:
        by_run.setdefault(step.run_id, []).append(step)
    return [_run_out(run, by_run.get(run.id, [])) for run in runs]


@router.post("/conversations/{conversation_id}/messages", response_model=ReplyOut)
async def send_message(
    conversation_id: uuid.UUID,
    body: MessageIn,
    response: Response,
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    principal: Principal = Depends(get_principal),
    who: Who = Depends(get_who),
    llm: LLMClient = Depends(get_llm),
    registry: ToolRegistry = Depends(get_registry),
    redis: Redis = Depends(get_redis),
    embedder: Embedder | None = Depends(get_embedder),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", min_length=1, max_length=200),
) -> ReplyOut:
    # Short transactions on purpose: nothing below holds a database transaction while the model thinks.
    settings = get_settings()
    async with tenant_session(tenant_id) as session:
        actor = await actor_for(session, principal)
        conversation = await _conversation_or_404(session, conversation_id)
        if actor.restricted and conversation.employee_id != actor.id:
            # Even support agents only talk to the agent in their own conversations.
            raise HTTPException(status_code=404, detail="Conversation not found")
        employee_id = conversation.employee_id

    # Cheap refusals first: a script gets turned away before it can cost anything.
    try:
        if who.session_id:
            await limits.hit(redis, f"rl:msg:s:{who.session_id}", settings.messages_per_minute_session, 60)
        await limits.hit(redis, f"rl:msg:ip:{who.ip}", settings.messages_per_minute_ip, 60)
        await limits.ensure_budget(redis, settings, who)
    except RedisError as exc:
        raise HTTPException(503, "The coordination service (Redis) is unavailable.") from exc

    claimed = False
    if idempotency_key:
        req_hash = idempotency.request_hash(conversation_id, body.content)
        async with tenant_session(tenant_id) as session:
            claim = await idempotency.claim(session, tenant_id, idempotency_key, req_hash)
        if claim.outcome == "replay":
            response.headers["Idempotent-Replay"] = "true"
            return ReplyOut.model_validate(claim.response)
        if claim.outcome == "mismatch":
            raise HTTPException(422, "This Idempotency-Key was already used with a different request.")
        if claim.outcome == "in_progress":
            raise HTTPException(409, "A request with this Idempotency-Key is still in progress.")
        claimed = True

    try:
        async with conversation_lock(
            redis, tenant_id, conversation_id, ttl_seconds=get_settings().conversation_lock_ttl_seconds
        ) as lock:
            result = await run_agent(
                scope=lambda: tenant_session(tenant_id),
                llm=llm,
                registry=registry,
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                employee_id=employee_id,
                user_text=body.content,
                max_steps=get_settings().agent_max_steps,
                heartbeat=lock.renew,
                embedder=embedder,
            )
    except ConversationBusy as exc:
        await _release_claim(tenant_id, idempotency_key, claimed)
        detail = "This conversation is already being processed. Try again in a moment."
        raise HTTPException(409, detail) from exc
    except RedisError as exc:
        await _release_claim(tenant_id, idempotency_key, claimed)
        raise HTTPException(503, "The coordination service (Redis) is unavailable.") from exc
    except LockLost as exc:
        await _release_claim(tenant_id, idempotency_key, claimed)
        raise HTTPException(409, "The conversation lock was lost while processing. Try again.") from exc
    except BaseException:
        await _release_claim(tenant_id, idempotency_key, claimed)
        raise

    try:
        await limits.record_spend(redis, who, result.cost_usd)
    except RedisError:
        logger.exception("Could not record spend for run %s", result.run_id)

    out = ReplyOut(
        reply=result.reply,
        run=RunSummary(
            run_id=result.run_id,
            status=result.status,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            cost_usd=result.cost_usd,
        ),
    )
    if claimed:
        if result.status == AgentRunStatus.failed:
            # A provider outage is worth retrying: free the key instead of replaying the failure forever.
            await _release_claim(tenant_id, idempotency_key, claimed)
        else:
            async with tenant_session(tenant_id) as session:
                await idempotency.complete(session, idempotency_key, out.model_dump(mode="json"))
    return out


async def _release_claim(tenant_id: uuid.UUID, key: str | None, claimed: bool) -> None:
    if claimed and key:
        async with tenant_session(tenant_id) as session:
            await idempotency.release(session, key)


@router.get("/runs/{run_id}", response_model=RunOut)
async def get_run(
    run_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> RunOut:
    run = await session.get(AgentRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    try:
        await _conversation_or_404(session, run.conversation_id, await actor_for(session, principal))
    except HTTPException:
        raise HTTPException(status_code=404, detail="Run not found") from None
    steps = await session.scalars(
        select(AgentStep).where(AgentStep.run_id == run_id).order_by(AgentStep.step_index)
    )
    return _run_out(run, list(steps))


def _run_out(run: AgentRun, steps: list[AgentStep]) -> RunOut:
    return RunOut(
        id=run.id,
        conversation_id=run.conversation_id,
        status=run.status,
        model=run.model,
        prompt_tokens=run.prompt_tokens,
        completion_tokens=run.completion_tokens,
        cost_usd=run.cost_usd,
        error=run.error,
        started_at=run.started_at,
        finished_at=run.finished_at,
        steps=[StepOut.model_validate(s) for s in steps],
    )
