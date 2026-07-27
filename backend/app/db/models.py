import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, ForeignKey, Text, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


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


TENANT_SCOPED_TABLES = [
    Employee.__tablename__,
    System.__tablename__,
    Conversation.__tablename__,
    Message.__tablename__,
    Ticket.__tablename__,
    TicketEvent.__tablename__,
    Escalation.__tablename__,
]
