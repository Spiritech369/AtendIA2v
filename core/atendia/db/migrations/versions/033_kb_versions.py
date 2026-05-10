"""033_kb_versions

Revision ID: dafa3c47b0bb
Revises: 78aea1a21131
Create Date: 2026-05-10
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "dafa3c47b0bb"
down_revision: str | Sequence[str] | None = "78aea1a21131"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "kb_versions",
        sa.Column("id", sa.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", sa.UUID(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("entity_type", sa.String(40), nullable=False),
        sa.Column("entity_id", sa.UUID(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("changed_by", sa.UUID()),
        sa.Column("change_summary", sa.Text()),
        sa.Column(
            "diff_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(
        "ix_kb_versions_entity",
        "kb_versions",
        ["tenant_id", "entity_type", "entity_id", sa.text("version_number DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_kb_versions_entity", table_name="kb_versions")
    op.drop_table("kb_versions")
