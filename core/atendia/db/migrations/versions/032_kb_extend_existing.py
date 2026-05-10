"""032_extend_existing — extend tenant_faqs/catalogs/documents/chunks for KB

Revision ID: 78aea1a21131
Revises: 4db7c9252065
Create Date: 2026-05-10
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "78aea1a21131"
down_revision: str | Sequence[str] | None = "4db7c9252065"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Subset of shared metadata columns — ``status`` is special-cased per-table
# because ``knowledge_documents.status`` already exists with the right
# semantics (just legacy values to migrate).
def _add_status(table: str) -> None:
    op.add_column(table, sa.Column("status", sa.String(20), nullable=False, server_default="published"))


def _add_shared_metadata_minus_status(table: str) -> None:
    op.add_column(table, sa.Column("visibility", sa.String(20), nullable=False, server_default="agents"))
    op.add_column(table, sa.Column("priority", sa.Integer(), nullable=False, server_default="0"))
    op.add_column(table, sa.Column("expires_at", sa.DateTime(timezone=True)))
    op.add_column(table, sa.Column("created_by", sa.UUID()))
    op.add_column(table, sa.Column("updated_by", sa.UUID()))
    op.add_column(table, sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")))
    op.add_column(
        table,
        sa.Column(
            "agent_permissions",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(table, sa.Column("collection_id", sa.UUID(), sa.ForeignKey("kb_collections.id", ondelete="SET NULL")))
    op.add_column(table, sa.Column("language", sa.String(8), nullable=False, server_default="es-MX"))


def upgrade() -> None:
    # tenant_faqs + tenant_catalogs need the full shared block including status.
    for table in ("tenant_faqs", "tenant_catalogs"):
        _add_status(table)
        _add_shared_metadata_minus_status(table)

    # knowledge_documents already has ``status``; only add the rest of shared.
    _add_shared_metadata_minus_status("knowledge_documents")

    # tenant_catalogs additions
    op.add_column("tenant_catalogs", sa.Column("price_cents", sa.BigInteger()))
    op.add_column("tenant_catalogs", sa.Column("stock_status", sa.String(20), nullable=False, server_default="unknown"))
    op.add_column("tenant_catalogs", sa.Column("region", sa.String(60)))
    op.add_column("tenant_catalogs", sa.Column("branch", sa.String(60)))
    op.add_column(
        "tenant_catalogs",
        sa.Column(
            "payment_plans",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )

    # knowledge_documents additions + status migration.
    op.add_column("knowledge_documents", sa.Column("progress_percentage", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("knowledge_documents", sa.Column("embedded_chunk_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("knowledge_documents", sa.Column("error_count", sa.Integer(), nullable=False, server_default="0"))
    # Migrate legacy 'indexed' -> 'ready' (status column already exists; widening the
    # enum is purely a value-set change since the column is String(20)).
    op.execute("UPDATE knowledge_documents SET status='ready' WHERE status='indexed'")
    op.execute("UPDATE knowledge_documents SET embedded_chunk_count=fragment_count WHERE status='ready'")

    # knowledge_chunks additions
    op.add_column("knowledge_chunks", sa.Column("chunk_status", sa.String(20), nullable=False, server_default="embedded"))
    op.add_column("knowledge_chunks", sa.Column("marked_critical", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("knowledge_chunks", sa.Column("error_message", sa.Text()))
    op.add_column("knowledge_chunks", sa.Column("token_count", sa.Integer()))
    op.add_column("knowledge_chunks", sa.Column("page", sa.Integer()))
    op.add_column("knowledge_chunks", sa.Column("heading", sa.Text()))
    op.add_column("knowledge_chunks", sa.Column("section", sa.Text()))
    op.add_column("knowledge_chunks", sa.Column("last_retrieved_at", sa.DateTime(timezone=True)))
    op.add_column("knowledge_chunks", sa.Column("retrieval_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("knowledge_chunks", sa.Column("average_score", sa.Float()))

    op.create_index("ix_kb_chunks_status", "knowledge_chunks", ["tenant_id", "chunk_status"])


def downgrade() -> None:
    op.drop_index("ix_kb_chunks_status", table_name="knowledge_chunks")
    for col in (
        "average_score", "retrieval_count", "last_retrieved_at",
        "section", "heading", "page", "token_count",
        "error_message", "marked_critical", "chunk_status",
    ):
        op.drop_column("knowledge_chunks", col)

    for col in ("error_count", "embedded_chunk_count", "progress_percentage"):
        op.drop_column("knowledge_documents", col)

    for col in ("payment_plans", "branch", "region", "stock_status", "price_cents"):
        op.drop_column("tenant_catalogs", col)

    shared_minus_status = (
        "language", "collection_id", "agent_permissions",
        "updated_at", "updated_by", "created_by",
        "expires_at", "priority", "visibility",
    )
    # Drop shared columns from all three tables. ``status`` only existed on
    # tenant_faqs/tenant_catalogs after upgrade — knowledge_documents had it
    # before this migration, so leave it alone.
    for col in shared_minus_status:
        op.drop_column("knowledge_documents", col)
    for table in ("tenant_catalogs", "tenant_faqs"):
        for col in shared_minus_status:
            op.drop_column(table, col)
        op.drop_column(table, "status")
