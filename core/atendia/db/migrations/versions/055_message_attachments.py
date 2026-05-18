"""055_message_attachments

Revision ID: u7i8j9k0l1m2
Revises: t6h7i8j9k0l1
Create Date: 2026-05-17

Persist message media as first-class attachments. The messages row keeps
metadata_json for backwards-compatible UI rendering, but the durable source
of truth for files is this table.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "u7i8j9k0l1m2"
down_revision: str | Sequence[str] | None = "t6h7i8j9k0l1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "message_attachments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("type", sa.String(length=20), nullable=False),
        sa.Column("mime_type", sa.String(length=120), nullable=False),
        sa.Column("storage_url", sa.Text(), nullable=False),
        sa.Column("caption", sa.Text(), nullable=True),
        sa.Column("original_filename", sa.String(length=255), nullable=True),
        sa.Column("file_size", sa.Integer(), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="ready"),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("type IN ('image', 'audio', 'document', 'video')", name="ck_message_attachments_type"),
        sa.CheckConstraint("status IN ('ready', 'failed')", name="ck_message_attachments_status"),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_message_attachments_message_id", "message_attachments", ["message_id"])
    op.create_index("ix_message_attachments_tenant_id", "message_attachments", ["tenant_id"])

    op.execute(
        """
        INSERT INTO message_attachments (
            message_id, tenant_id, type, mime_type, storage_url, caption,
            original_filename, file_size, status, metadata_json
        )
        SELECT
            id,
            tenant_id,
            COALESCE(metadata_json #>> '{media,type}', 'document'),
            COALESCE(metadata_json #>> '{media,mime_type}', 'application/octet-stream'),
            metadata_json #>> '{media,url}',
            metadata_json #>> '{media,caption}',
            metadata_json #>> '{media,original_filename}',
            NULLIF(metadata_json #>> '{media,file_size}', '')::integer,
            'ready',
            jsonb_build_object('source', 'metadata_backfill')
        FROM messages
        WHERE metadata_json ? 'media'
          AND metadata_json #>> '{media,url}' IS NOT NULL
          AND metadata_json #>> '{media,url}' <> ''
        """
    )


def downgrade() -> None:
    op.drop_index("ix_message_attachments_tenant_id", table_name="message_attachments")
    op.drop_index("ix_message_attachments_message_id", table_name="message_attachments")
    op.drop_table("message_attachments")
