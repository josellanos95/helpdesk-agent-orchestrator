"""approvals, audit log and support agents

Revision ID: 9d4a7c12e5b3
Revises: 7be41d2a6c05
Create Date: 2026-10-31 18:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.config import APP_DB_ROLE

# revision identifiers, used by Alembic.
revision: str = '9d4a7c12e5b3'
down_revision: str | None = '7be41d2a6c05'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_TABLES = ["approvals", "audit_log"]


def upgrade() -> None:
    op.add_column(
        'employees',
        sa.Column('is_support_agent', sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    # The demo tenants already have people whose job is support; mark them.
    op.execute(
        "UPDATE employees SET is_support_agent = true "
        "WHERE job_title IN ('IT Support Analyst', 'Support Agent')"
    )

    approval_status = postgresql.ENUM('pending', 'approved', 'rejected', 'expired', name='approval_status')
    op.create_table('approvals',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('conversation_id', sa.UUID(), nullable=False),
    sa.Column('requested_by', sa.UUID(), nullable=False),
    sa.Column('tool_call_id', sa.Text(), nullable=False),
    sa.Column('tool_name', sa.Text(), nullable=False),
    sa.Column('arguments', sa.Text(), nullable=False),
    sa.Column('status', approval_status, nullable=False),
    sa.Column('decided_by', sa.UUID(), nullable=True),
    sa.Column('decision_note', sa.Text(), nullable=True),
    sa.Column('result', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('expires_at', sa.DateTime(), nullable=False),
    sa.Column('decided_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], name=op.f('fk_approvals_conversation_id_conversations'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['decided_by'], ['employees.id'], name=op.f('fk_approvals_decided_by_employees'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['requested_by'], ['employees.id'], name=op.f('fk_approvals_requested_by_employees'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], name=op.f('fk_approvals_tenant_id_tenants'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_approvals')),
    sa.UniqueConstraint('tenant_id', 'conversation_id', 'tool_call_id', name='uq_approvals_call')
    )
    op.create_index(op.f('ix_approvals_tenant_id'), 'approvals', ['tenant_id'], unique=False)

    op.create_table('audit_log',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('actor_id', sa.UUID(), nullable=True),
    sa.Column('actor_type', sa.Text(), nullable=False),
    sa.Column('action', sa.Text(), nullable=False),
    sa.Column('subject', sa.Text(), nullable=False),
    sa.Column('details', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['actor_id'], ['employees.id'], name=op.f('fk_audit_log_actor_id_employees'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], name=op.f('fk_audit_log_tenant_id_tenants'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_audit_log'))
    )
    op.create_index(op.f('ix_audit_log_tenant_id'), 'audit_log', ['tenant_id'], unique=False)

    for table in NEW_TABLES:
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO {APP_DB_ROLE}")
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"""
            CREATE POLICY tenant_isolation ON {table}
            USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
            WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid)
        """)


def downgrade() -> None:
    for table in NEW_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
    op.drop_index(op.f('ix_audit_log_tenant_id'), table_name='audit_log')
    op.drop_table('audit_log')
    op.drop_index(op.f('ix_approvals_tenant_id'), table_name='approvals')
    op.drop_table('approvals')
    # Autogenerate does not drop enum types with their table (ADR 0001, bug 4).
    op.execute("DROP TYPE IF EXISTS approval_status")
    op.drop_column('employees', 'is_support_agent')
