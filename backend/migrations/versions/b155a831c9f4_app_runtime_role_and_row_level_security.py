"""app_runtime role and row level security

Creates a dedicated, least-privilege Postgres role (app_runtime) that the
FastAPI app connects as at request time, and enables + FORCES Row Level
Security on every tenant-scoped table.

FORCE matters: Postgres exempts the table owner from RLS unless the table is
FORCE'd, and even then, superusers and roles with BYPASSRLS are *always*
exempt regardless of FORCE. That's why the app must never connect using the
admin/owner role used for migrations — see docs/adr/0001-multi-tenant-isolation-via-rls.md.

Revision ID: b155a831c9f4
Revises: d1e61f5df3c3
Create Date: 2026-07-27 20:29:50.049973

"""
from collections.abc import Sequence

from alembic import op

from app.config import APP_DB_ROLE, get_settings

# Frozen on purpose. This used to import TENANT_SCOPED_TABLES from the models,
# which silently changes what an *old* migration does whenever a table is added
# later: a fresh `alembic upgrade head` would try to enable RLS on tables that
# don't exist yet at this revision. Later tables get RLS in their own migration.
TENANT_SCOPED_TABLES = [
    "employees",
    "systems",
    "conversations",
    "messages",
    "tickets",
    "ticket_events",
    "escalations",
]

# revision identifiers, used by Alembic.
revision: str = 'b155a831c9f4'
down_revision: str | None = 'd1e61f5df3c3'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    password = get_settings().app_db_password.replace("'", "''")

    op.execute(f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '{APP_DB_ROLE}') THEN
                CREATE ROLE {APP_DB_ROLE} LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
            END IF;
        END
        $$;
    """)
    # Kept as a separate statement (not inside the DO block) so re-running this
    # migration's upgrade on a fresh env resyncs the password to match app_db_password.
    op.execute(f"ALTER ROLE {APP_DB_ROLE} WITH PASSWORD '{password}'")

    # CONNECT on the database is granted to PUBLIC by default in Postgres, so
    # app_runtime already has it — nothing to do there.
    op.execute(f"GRANT USAGE ON SCHEMA public TO {APP_DB_ROLE}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {APP_DB_ROLE}")
    op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {APP_DB_ROLE}")

    for table in TENANT_SCOPED_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        # current_setting(..., true) suppresses the "unrecognized configuration
        # parameter" error, but an unset GUC still reads back as '' — casting
        # '' to uuid raises invalid_text_representation. So forgetting to SET
        # LOCAL app.tenant_id doesn't leak rows or silently return zero rows,
        # it fails the query outright. Verified manually: see docs/adr/0001.
        op.execute(f"""
            CREATE POLICY tenant_isolation ON {table}
            USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
            WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid)
        """)


def downgrade() -> None:
    for table in TENANT_SCOPED_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    # ALTER DEFAULT PRIVILEGES leaves a dependency owned by the migration role
    # (here: whoever ran upgrade()) that blocks DROP ROLE until it's undone —
    # a plain REVOKE on existing tables is not enough.
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM {APP_DB_ROLE}"
    )
    op.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {APP_DB_ROLE}")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {APP_DB_ROLE}")
    op.execute(f"DROP ROLE IF EXISTS {APP_DB_ROLE}")
