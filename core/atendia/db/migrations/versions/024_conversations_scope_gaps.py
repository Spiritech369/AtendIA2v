"""024_conversations_scope_gaps

Revision ID: a1b2c3d4e5f6
Revises: f9a0b1c2d3e4
Create Date: 2026-05-08

Adds assigned_user_id, unread_count, tags, deleted_at to conversations
for v1 parity: agent assignment, unread badges, free-form tags, soft delete.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: str | Sequence[str] | None = "f9a0b1c2d3e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column(
            "assigned_user_id",
            sa.UUID(),
            sa.ForeignKey("tenant_users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "conversations",
        sa.Column("unread_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "conversations",
        sa.Column(
            "tags",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default="[]",
        ),
    )
    op.add_column(
        "conversations",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "idx_conversations_assigned_user_id",
        "conversations",
        ["assigned_user_id"],
    )
    op.create_index(
        "idx_conversations_not_deleted",
        "conversations",
        ["tenant_id"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_conversations_not_deleted")
    op.drop_index("idx_conversations_assigned_user_id")
    op.drop_column("conversations", "deleted_at")
    op.drop_column("conversations", "tags")
    op.drop_column("conversations", "unread_count")
    op.drop_column("conversations", "assigned_user_id")
