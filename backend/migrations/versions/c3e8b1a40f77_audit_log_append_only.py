"""audit log is append-only for the runtime role

Revision ID: c3e8b1a40f77
Revises: 9d4a7c12e5b3
Create Date: 2026-10-31 19:00:00.000000

"""
from collections.abc import Sequence

from alembic import op

from app.config import APP_DB_ROLE

# revision identifiers, used by Alembic.
revision: str = 'c3e8b1a40f77'
down_revision: str | None = '9d4a7c12e5b3'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The app can add and read audit entries but never edit or erase them, even if a bug or an
    # injected instruction tried to. Cascading deletes when a tenant is removed run as the owner.
    op.execute(f"REVOKE UPDATE, DELETE ON audit_log FROM {APP_DB_ROLE}")


def downgrade() -> None:
    op.execute(f"GRANT UPDATE, DELETE ON audit_log TO {APP_DB_ROLE}")
