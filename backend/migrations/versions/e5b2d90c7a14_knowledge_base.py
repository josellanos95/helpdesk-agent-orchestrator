"""knowledge base: articles and embedded chunks (pgvector + full text)

Revision ID: e5b2d90c7a14
Revises: c3e8b1a40f77
Create Date: 2026-10-31 21:00:00.000000

"""
from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.config import APP_DB_ROLE

# revision identifiers, used by Alembic.
revision: str = 'e5b2d90c7a14'
down_revision: str | None = 'c3e8b1a40f77'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_TABLES = ["kb_articles", "kb_chunks"]
DIMENSIONS = 1536


def upgrade() -> None:
    # Needs a role allowed to create extensions (the owner/admin connection migrations already use).
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table('kb_articles',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('title', sa.Text(), nullable=False),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('content_hash', sa.Text(), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['employees.id'], name=op.f('fk_kb_articles_created_by_employees'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], name=op.f('fk_kb_articles_tenant_id_tenants'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_kb_articles')),
    sa.UniqueConstraint('tenant_id', 'title', name='uq_kb_articles_title')
    )
    op.create_index(op.f('ix_kb_articles_tenant_id'), 'kb_articles', ['tenant_id'], unique=False)

    op.create_table('kb_chunks',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('article_id', sa.UUID(), nullable=False),
    sa.Column('chunk_index', sa.Integer(), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('embedding_model', sa.Text(), nullable=False),
    sa.Column('embedding', pgvector.sqlalchemy.Vector(DIMENSIONS), nullable=False),
    sa.Column('tsv', postgresql.TSVECTOR(), sa.Computed("to_tsvector('english', content)", persisted=True), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['article_id'], ['kb_articles.id'], name=op.f('fk_kb_chunks_article_id_kb_articles'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], name=op.f('fk_kb_chunks_tenant_id_tenants'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_kb_chunks'))
    )
    op.create_index(op.f('ix_kb_chunks_tenant_id'), 'kb_chunks', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_kb_chunks_article_id'), 'kb_chunks', ['article_id'], unique=False)
    op.create_index('ix_kb_chunks_tsv', 'kb_chunks', ['tsv'], unique=False, postgresql_using='gin')
    # No ANN (HNSW/IVFFlat) index on purpose: with Row Level Security the filter is applied after an
    # approximate scan, so a small tenant can get fewer results than it has. Per-tenant knowledge bases
    # are small; exact search filtered by tenant is correct and fast. See docs/adr/0005.

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
    op.drop_index('ix_kb_chunks_tsv', table_name='kb_chunks', postgresql_using='gin')
    op.drop_index(op.f('ix_kb_chunks_article_id'), table_name='kb_chunks')
    op.drop_index(op.f('ix_kb_chunks_tenant_id'), table_name='kb_chunks')
    op.drop_table('kb_chunks')
    op.drop_index(op.f('ix_kb_articles_tenant_id'), table_name='kb_articles')
    op.drop_table('kb_articles')
    # The extension is left installed: other databases/objects on the server may use it.
