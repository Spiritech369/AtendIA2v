"""031_kb_collections

Revision ID: 4db7c9252065
Revises: a7b8c9d0e1f2
Create Date: 2026-05-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "4db7c9252065"
down_revision: str | Sequence[str] | None = "a7b8c9d0e1f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "kb_collections",
        sa.Column("id", sa.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "tenant_id", sa.UUID(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("slug", sa.String(60), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("icon", sa.String(40)),
        sa.Column("color", sa.String(20)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "uq_kb_collections_tenant_slug",
        "kb_collections",
        ["tenant_id", "slug"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_kb_collections_tenant_slug", table_name="kb_collections")
    op.drop_table("kb_collections")
