import enum
import uuid
from datetime import datetime
from decimal import Decimal

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Computed,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    false,
    func,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

EMBEDDING_DIMENSIONS = 1536  # text-embedding-3-small; changing it needs a migration


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class SystemStatus(str, enum.Enum):
    operational = "operational"
    degraded = "degraded"
    outage = "outage"


class MessageRole(str, enum.Enum):
    user = "user"
    assistant = "assistant"
    tool = "tool"


class TicketCategory(str, enum.Enum):
    password_reset = "password_reset"
    access_request = "access_request"
    hardware = "hardware"
    software = "software"
    network = "network"
    other = "other"


class TicketPriority(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"
    urgent = "urgent"


class TicketStatus(str, enum.Enum):
    open = "open"
    in_progress = "in_progress"
    escalated = "escalated"
    resolved = "resolved"
    closed = "closed"


class EscalationStatus(str, enum.Enum):
    pending = "pending"
    acknowledged = "acknowledged"
    resolved = "resolved"


class ApprovalStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    expired = "expired"


class AgentRunStatus(str, enum.Enum):
    running = "running"
    completed = "completed"
    failed = "failed"
    max_steps = "max_steps"


class Tenant(Base):
    """Not RLS-scoped: this is the root of the tenancy tree, resolved before RLS applies."""

    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    employees: Mapped[list["Employee"]] = relationship(back_populates="tenant")


class Employee(Base):
    __tablename__ = "employees"

    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    job_title: Mapped[str] = mapped_column(Text, nullable=False)
    # Human agents who can decide approvals and work the escalation queue.
    is_support_agent: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    tenant: Mapped["Tenant"] = relationship(back_populates="employees")


class System(Base):
    """Simulated internal IT system whose status the agent can check (VPN, email, CRM, ...)."""

    __tablename__ = "systems"

    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[SystemStatus] = mapped_column(
        SAEnum(SystemStatus, name="system_status"), nullable=False, default=SystemStatus.operational
    )
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(server_default=func.now())
    last_message_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    messages: Mapped[list["Message"]] = relationship(back_populates="conversation")


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = _uuid_pk()
    # Total order of messages. created_at can't do it: now() is the *transaction* start,
    # so every message written during one request shares the same timestamp.
    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True), nullable=False)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[MessageRole] = mapped_column(SAEnum(MessageRole, name="message_role"), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tool_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    tool_call_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    # On assistant messages that asked for tools: [{"id", "name", "arguments"}], so the
    # exact history can be replayed to the model on the next turn.
    tool_calls: Mapped[list | None] = mapped_column(JSONB().with_variant(JSON, "sqlite"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")


class Ticket(Base):
    __tablename__ = "tickets"

    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True
    )
    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )
    category: Mapped[TicketCategory] = mapped_column(
        SAEnum(TicketCategory, name="ticket_category"), nullable=False
    )
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[TicketPriority] = mapped_column(
        SAEnum(TicketPriority, name="ticket_priority"), nullable=False, default=TicketPriority.medium
    )
    status: Mapped[TicketStatus] = mapped_column(
        SAEnum(TicketStatus, name="ticket_status"), nullable=False, default=TicketStatus.open
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class TicketEvent(Base):
    __tablename__ = "ticket_events"

    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ticket_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB().with_variant(JSON, "sqlite"), nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Escalation(Base):
    __tablename__ = "escalations"

    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ticket_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    urgency: Mapped[TicketPriority] = mapped_column(
        SAEnum(TicketPriority, name="ticket_priority"), nullable=False, default=TicketPriority.medium
    )
    status: Mapped[EscalationStatus] = mapped_column(
        SAEnum(EscalationStatus, name="escalation_status"), nullable=False, default=EscalationStatus.pending
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(nullable=True)


class AgentRun(Base):
    """One execution of the agent loop for one user message. Its steps are the trace."""

    __tablename__ = "agent_runs"

    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[AgentRunStatus] = mapped_column(
        SAEnum(AgentRunStatus, name="agent_run_status"), nullable=False, default=AgentRunStatus.running
    )
    model: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False, default=Decimal(0))
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)

    steps: Mapped[list["AgentStep"]] = relationship(
        back_populates="run", order_by="AgentStep.step_index"
    )


class AgentStep(Base):
    """A single LLM call or tool call inside a run."""

    __tablename__ = "agent_steps"

    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    step_index: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)  # "llm" | "tool"
    name: Mapped[str] = mapped_column(Text, nullable=False)  # model id, or tool name
    input: Mapped[dict | list | None] = mapped_column(JSONB().with_variant(JSON, "sqlite"), nullable=True)
    output: Mapped[dict | list | None] = mapped_column(JSONB().with_variant(JSON, "sqlite"), nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    run: Mapped["AgentRun"] = relationship(back_populates="steps")


class ToolExecution(Base):
    """Ledger that makes a tool call run at most once per (conversation, tool_call_id).

    The row is claimed, the tool runs and the result is stored in ONE transaction, so a committed
    row always has its result and a rolled-back attempt leaves nothing behind.
    """

    __tablename__ = "tool_executions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "conversation_id", "tool_call_id", name="uq_tool_executions_call"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    tool_call_id: Mapped[str] = mapped_column(Text, nullable=False)
    tool_name: Mapped[str] = mapped_column(Text, nullable=False)
    arguments: Mapped[str] = mapped_column(Text, nullable=False)
    result: Mapped[dict | None] = mapped_column(JSONB().with_variant(JSON, "sqlite"), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class IdempotencyKey(Base):
    """Request-level idempotency for POST .../messages (the Idempotency-Key header)."""

    __tablename__ = "idempotency_keys"
    __table_args__ = (UniqueConstraint("tenant_id", "key", name="uq_idempotency_keys_key"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    key: Mapped[str] = mapped_column(Text, nullable=False)
    request_hash: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)  # "in_progress" | "completed"
    response: Mapped[dict | None] = mapped_column(JSONB().with_variant(JSON, "sqlite"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Approval(Base):
    """A sensitive tool call the agent asked for and a human has to decide.

    While pending nothing has run. On approval the tool executes through the tool ledger using the
    original tool_call_id, so deciding twice (a double click, two agents, a retry) executes once.
    """

    __tablename__ = "approvals"
    __table_args__ = (
        UniqueConstraint("tenant_id", "conversation_id", "tool_call_id", name="uq_approvals_call"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    requested_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )
    tool_call_id: Mapped[str] = mapped_column(Text, nullable=False)
    tool_name: Mapped[str] = mapped_column(Text, nullable=False)
    arguments: Mapped[str] = mapped_column(Text, nullable=False)  # validated, normalised JSON
    status: Mapped[ApprovalStatus] = mapped_column(
        SAEnum(ApprovalStatus, name="approval_status"), nullable=False, default=ApprovalStatus.pending
    )
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True
    )
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    result: Mapped[dict | None] = mapped_column(JSONB().with_variant(JSON, "sqlite"), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(nullable=True)


class AuditLog(Base):
    """Append-only record of sensitive actions and of who decided them."""

    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True
    )
    actor_type: Mapped[str] = mapped_column(Text, nullable=False)  # "human" | "agent" | "system"
    action: Mapped[str] = mapped_column(Text, nullable=False)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[dict] = mapped_column(JSONB().with_variant(JSON, "sqlite"), nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class KbArticle(Base):
    """A help article a tenant's support team wrote. The agent answers from these, not from memory."""

    __tablename__ = "kb_articles"
    __table_args__ = (UniqueConstraint("tenant_id", "title", name="uq_kb_articles_title"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    # sha256 of (embedding model, title, body): re-saving identical content does not pay to re-embed.
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class KbChunk(Base):
    """One passage of an article with its embedding and a full-text vector (hybrid search)."""

    __tablename__ = "kb_chunks"
    __table_args__ = (Index("ix_kb_chunks_tsv", "tsv", postgresql_using="gin"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    article_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("kb_articles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # Which model produced `embedding`. Search only compares vectors from the same model.
    embedding_model: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSIONS), nullable=False)
    tsv: Mapped[str] = mapped_column(
        TSVECTOR, Computed("to_tsvector('english', content)", persisted=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


TENANT_SCOPED_TABLES = [
    Employee.__tablename__,
    System.__tablename__,
    Conversation.__tablename__,
    Message.__tablename__,
    Ticket.__tablename__,
    TicketEvent.__tablename__,
    Escalation.__tablename__,
    AgentRun.__tablename__,
    AgentStep.__tablename__,
    ToolExecution.__tablename__,
    IdempotencyKey.__tablename__,
    Approval.__tablename__,
    AuditLog.__tablename__,
    KbArticle.__tablename__,
    KbChunk.__tablename__,
]
