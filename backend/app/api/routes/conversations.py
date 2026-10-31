import uuid
from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.runner import run_agent
from app.agent.tools import ToolRegistry, default_registry
from app.api.deps import get_db, get_llm, get_tenant_id
from app.config import get_settings
from app.db.models import AgentRun, AgentRunStatus, AgentStep, Conversation, Employee, Message, MessageRole
from app.llm.base import LLMClient

router = APIRouter()


class EmployeeOut(BaseModel):
    id: uuid.UUID
    full_name: str
    email: str
    job_title: str

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
    session: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    llm: LLMClient = Depends(get_llm),
    registry: ToolRegistry = Depends(get_registry),
) -> ReplyOut:
    conversation = await _conversation_or_404(session, conversation_id)
    employee = await session.get(Employee, conversation.employee_id)
    result = await run_agent(
        session=session,
        llm=llm,
        registry=registry,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        employee=employee,
        user_text=body.content,
        max_steps=get_settings().agent_max_steps,
    )
    return ReplyOut(
        reply=result.reply,
        run=RunSummary(
            run_id=result.run_id,
            status=result.status,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            cost_usd=result.cost_usd,
        ),
    )


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
