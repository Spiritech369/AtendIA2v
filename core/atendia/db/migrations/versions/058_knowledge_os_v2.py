"""058_knowledge_os_v2

Knowledge OS v2 base tables:
- knowledge_sources
- knowledge_items
- knowledge_os_chunks
- knowledge_retrieval_logs
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import HALFVEC  # type: ignore[import-untyped]
from sqlalchemy.dialects import postgresql

revision: str = "x0y1z2a3b4c5"
down_revision: str | Sequence[str] | None = "w9k0l1m2n3o4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "knowledge_sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=240), nullable=False),
        sa.Column("type", sa.String(length=40), nullable=False),
        sa.Column("content_type", sa.String(length=60), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="draft"),
        sa.Column("owner", sa.String(length=160), nullable=True),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "type IN ('file', 'url', 'faq', 'table', 'manual')",
            name="ck_knowledge_sources_type",
        ),
        sa.CheckConstraint(
            "content_type IN "
            "('faq', 'policy', 'credit_policy', 'pricing', 'catalog', 'services', "
            "'appointment_rules', 'document_rules', 'location_hours', "
            "'inventory_color_policy', 'general')",
            name="ck_knowledge_sources_content_type",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'processing', 'active', 'error', 'stale', 'expired')",
            name="ck_knowledge_sources_status",
        ),
    )
    op.create_index("ix_knowledge_sources_tenant_id", "knowledge_sources", ["tenant_id"])
    op.create_index("ix_knowledge_sources_status", "knowledge_sources", ["status"])

    op.create_table(
        "knowledge_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("structured_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="active"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["knowledge_sources.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_knowledge_items_tenant_id", "knowledge_items", ["tenant_id"])
    op.create_index("ix_knowledge_items_source_id", "knowledge_items", ["source_id"])

    op.create_table(
        "knowledge_os_chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chunk_text", sa.Text(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("embedding", HALFVEC(3072), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="active"),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["knowledge_sources.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["item_id"], ["knowledge_items.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_knowledge_os_chunks_tenant_id", "knowledge_os_chunks", ["tenant_id"])
    op.create_index("ix_knowledge_os_chunks_source_id", "knowledge_os_chunks", ["source_id"])
    op.create_index("ix_knowledge_os_chunks_item_id", "knowledge_os_chunks", ["item_id"])

    op.create_table(
        "knowledge_retrieval_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("answerable", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column(
            "selected_chunk_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "citations_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "ix_knowledge_retrieval_logs_tenant_id",
        "knowledge_retrieval_logs",
        ["tenant_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_knowledge_retrieval_logs_tenant_id", table_name="knowledge_retrieval_logs")
    op.drop_table("knowledge_retrieval_logs")
    op.drop_index("ix_knowledge_os_chunks_item_id", table_name="knowledge_os_chunks")
    op.drop_index("ix_knowledge_os_chunks_source_id", table_name="knowledge_os_chunks")
    op.drop_index("ix_knowledge_os_chunks_tenant_id", table_name="knowledge_os_chunks")
    op.drop_table("knowledge_os_chunks")
    op.drop_index("ix_knowledge_items_source_id", table_name="knowledge_items")
    op.drop_index("ix_knowledge_items_tenant_id", table_name="knowledge_items")
    op.drop_table("knowledge_items")
    op.drop_index("ix_knowledge_sources_status", table_name="knowledge_sources")
    op.drop_index("ix_knowledge_sources_tenant_id", table_name="knowledge_sources")
    op.drop_table("knowledge_sources")
