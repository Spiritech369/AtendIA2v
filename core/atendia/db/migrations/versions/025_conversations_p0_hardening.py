"""025_conversations_p0_hardening

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-05-08

P0 hardening for conversations:
- per-user read state
- indexes for tenant-scoped conversation inbox/board queries
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b2c3d4e5f6a7"
down_revision: str | Sequence[str] | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "conversation_reads",
        sa.Column(
            "tenant_id",
            sa.UUID(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "conversation_id",
            sa.UUID(),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.UUID(),
            sa.ForeignKey("tenant_users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "last_read_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "last_read_message_id",
            sa.UUID(),
            sa.ForeignKey("messages.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("conversation_id", "user_id"),
    )
    op.create_index(
        "idx_conversation_reads_tenant_user",
        "conversation_reads",
        ["tenant_id", "user_id"],
    )
    op.create_index(
        "idx_conversations_tenant_deleted_activity",
        "conversations",
        ["tenant_id", "deleted_at", "last_activity_at"],
    )
    op.create_index(
        "idx_conversations_tenant_customer_deleted_activity",
        "conversations",
        ["tenant_id", "customer_id", "deleted_at", "last_activity_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_conversations_tenant_customer_deleted_activity")
    op.drop_index("idx_conversations_tenant_deleted_activity")
    op.drop_index("idx_conversation_reads_tenant_user")
    op.drop_table("conversation_reads")
