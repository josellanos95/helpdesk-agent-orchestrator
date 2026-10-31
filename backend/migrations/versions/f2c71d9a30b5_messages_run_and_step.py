"""messages remember the run and step that produced them

Revision ID: f2c71d9a30b5
Revises: e5b2d90c7a14
Create Date: 2026-11-01 10:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'f2c71d9a30b5'
down_revision: str | None = 'e5b2d90c7a14'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('messages', sa.Column('run_id', sa.UUID(), nullable=True))
    op.add_column('messages', sa.Column('step_index', sa.Integer(), nullable=True))
    op.create_foreign_key(
        op.f('fk_messages_run_id_agent_runs'), 'messages', 'agent_runs', ['run_id'], ['id'], ondelete='SET NULL'
    )


def downgrade() -> None:
    op.drop_constraint(op.f('fk_messages_run_id_agent_runs'), 'messages', type_='foreignkey')
    op.drop_column('messages', 'step_index')
    op.drop_column('messages', 'run_id')
