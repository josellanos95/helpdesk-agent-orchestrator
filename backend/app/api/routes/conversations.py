import uuid
from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import BaseModel, Field
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.runner import run_agent
from app.agent.tools import ToolRegistry, default_registry
from app.api.deps import get_db, get_embedder, get_llm, get_redis, get_tenant_id
from app.config import get_settings
from app.db.models import AgentRun, AgentRunStatus, AgentStep, Conversation, Employee, Message, MessageRole
from app.db.session import tenant_session
from app.llm.base import LLMClient
from app.llm.embeddings import Embedder
from app.services import idempotency
from app.services.locks import ConversationBusy, LockLost, conversation_lock

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


class MessageOut(BaseModel):
    role: MessageRole
    content: str
    tool_name: str | None = None
    tool_calls: list | None = None
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


async def _conversation_or_404(session: AsyncSession, conversation_id: uuid.UUID) -> Conversation:
    # Another tenant's conversation is invisible under RLS, so it is indistinguishable from a missing one.
    conversation = await session.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


@router.get("/employees", response_model=list[EmployeeOut])
async def list_employees(session: AsyncSession = Depends(get_db)) -> list[Employee]:
    return list(await session.scalars(select(Employee).order_by(Employee.full_name)))


@router.post("/conversations", response_model=ConversationOut, status_code=201)
async def create_conversation(body: ConversationCreate, session: AsyncSession = Depends(get_db),
                              tenant_id: uuid.UUID = Depends(get_tenant_id)) -> Conversation:
    if await session.get(Employee, body.employee_id) is None:
        raise HTTPException(status_code=404, detail="Employee not found")
    conversation = Conversation(tenant_id=tenant_id, employee_id=body.employee_id)
    session.add(conversation)
    await session.flush()
    return conversation


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageOut])
async def list_messages(conversation_id: uuid.UUID, session: AsyncSession = Depends(get_db)) -> list[Message]:
    await _conversation_or_404(session, conversation_id)
    rows = await session.scalars(
        select(Message).where(Message.conversation_id == conversation_id).order_by(Message.seq)
    )
    return list(rows)


@router.post("/conversations/{conversation_id}/messages", response_model=ReplyOut)
async def send_message(
    conversation_id: uuid.UUID,
    body: MessageIn,
    response: Response,
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    llm: LLMClient = Depends(get_llm),
    registry: ToolRegistry = Depends(get_registry),
    redis: Redis = Depends(get_redis),
    embedder: Embedder | None = Depends(get_embedder),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", min_length=1, max_length=200),
) -> ReplyOut:
    # Short transactions on purpose: nothing below holds a database transaction while the model thinks.
    async with tenant_session(tenant_id) as session:
        conversation = await _conversation_or_404(session, conversation_id)
        employee_id = conversation.employee_id

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
async def get_run(run_id: uuid.UUID, session: AsyncSession = Depends(get_db)) -> RunOut:
    run = await session.get(AgentRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    steps = await session.scalars(
        select(AgentStep).where(AgentStep.run_id == run_id).order_by(AgentStep.step_index)
    )
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
