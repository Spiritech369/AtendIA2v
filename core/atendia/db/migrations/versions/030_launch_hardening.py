"""030_launch_hardening

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-05-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a7b8c9d0e1f2"
down_revision: str | Sequence[str] | None = "f6a7b8c9d0e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "outbound_outbox",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=220), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("channel_message_id", sa.String(length=120), nullable=True),
        sa.Column("sent_message_id", sa.UUID(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True
        ),
        sa.ForeignKeyConstraint(["sent_message_id"], ["messages.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_outbound_outbox_idempotency_key"),
    )
    op.create_index("ix_outbound_outbox_tenant_id", "outbound_outbox", ["tenant_id"])
    op.create_index(
        "ix_outbound_outbox_status_available", "outbound_outbox", ["status", "available_at"]
    )

    op.add_column(
        "workflow_event_cursors",
        sa.Column("last_created_at", sa.DateTime(timezone=True), nullable=True),
    )

    with op.get_context().autocommit_block():
        op.execute(
            "CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS "
            "uq_messages_tenant_channel_message_id "
            "ON messages (tenant_id, channel_message_id) "
            "WHERE channel_message_id IS NOT NULL"
        )
        op.execute(
            "CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS "
            "uq_appointments_tenant_customer_time_service_active "
            "ON appointments (tenant_id, customer_id, scheduled_at, service) "
            "WHERE deleted_at IS NULL"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            "DROP INDEX CONCURRENTLY IF EXISTS uq_appointments_tenant_customer_time_service_active"
        )
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS uq_messages_tenant_channel_message_id")

    op.drop_column("workflow_event_cursors", "last_created_at")
    op.drop_index("ix_outbound_outbox_status_available", table_name="outbound_outbox")
    op.drop_index("ix_outbound_outbox_tenant_id", table_name="outbound_outbox")
    op.drop_table("outbound_outbox")
