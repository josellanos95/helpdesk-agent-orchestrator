"""tool executions ledger and idempotency keys

Revision ID: 7be41d2a6c05
Revises: 3a7c1e5b9d20
Create Date: 2026-10-31 14:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.config import APP_DB_ROLE

# revision identifiers, used by Alembic.
revision: str = '7be41d2a6c05'
down_revision: str | None = '3a7c1e5b9d20'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_TABLES = ["tool_executions", "idempotency_keys"]


def upgrade() -> None:
    op.create_table('tool_executions',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('conversation_id', sa.UUID(), nullable=False),
    sa.Column('tool_call_id', sa.Text(), nullable=False),
    sa.Column('tool_name', sa.Text(), nullable=False),
    sa.Column('arguments', sa.Text(), nullable=False),
    sa.Column('result', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], name=op.f('fk_tool_executions_conversation_id_conversations'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], name=op.f('fk_tool_executions_tenant_id_tenants'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_tool_executions')),
    sa.UniqueConstraint('tenant_id', 'conversation_id', 'tool_call_id', name='uq_tool_executions_call')
    )
    op.create_index(op.f('ix_tool_executions_tenant_id'), 'tool_executions', ['tenant_id'], unique=False)

    op.create_table('idempotency_keys',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('key', sa.Text(), nullable=False),
    sa.Column('request_hash', sa.Text(), nullable=False),
    sa.Column('status', sa.Text(), nullable=False),
    sa.Column('response', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], name=op.f('fk_idempotency_keys_tenant_id_tenants'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_idempotency_keys')),
    sa.UniqueConstraint('tenant_id', 'key', name='uq_idempotency_keys_key')
    )
    op.create_index(op.f('ix_idempotency_keys_tenant_id'), 'idempotency_keys', ['tenant_id'], unique=False)

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
    op.drop_index(op.f('ix_idempotency_keys_tenant_id'), table_name='idempotency_keys')
    op.drop_table('idempotency_keys')
    op.drop_index(op.f('ix_tool_executions_tenant_id'), table_name='tool_executions')
    op.drop_table('tool_executions')
