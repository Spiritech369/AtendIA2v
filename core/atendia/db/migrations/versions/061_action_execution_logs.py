"""061_action_execution_logs

Audit log for AgentRuntime v2 post-turn action execution.
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "ac710nexecv2"
down_revision: str | Sequence[str] | None = "l1fecyc1ev2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "action_execution_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action_id", sa.String(length=120), nullable=False),
        sa.Column(
            "input",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column(
            "result",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("dry_run", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("trace_id", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_action_execution_logs_tenant_id", "action_execution_logs", ["tenant_id"])
    op.create_index(
        "ix_action_execution_logs_conversation_id",
        "action_execution_logs",
        ["conversation_id"],
    )
    op.create_index("ix_action_execution_logs_action_id", "action_execution_logs", ["action_id"])
    op.create_index("ix_action_execution_logs_status", "action_execution_logs", ["status"])
    op.create_index("ix_action_execution_logs_trace_id", "action_execution_logs", ["trace_id"])


def downgrade() -> None:
    op.drop_index("ix_action_execution_logs_trace_id", table_name="action_execution_logs")
    op.drop_index("ix_action_execution_logs_status", table_name="action_execution_logs")
    op.drop_index("ix_action_execution_logs_action_id", table_name="action_execution_logs")
    op.drop_index(
        "ix_action_execution_logs_conversation_id",
        table_name="action_execution_logs",
    )
    op.drop_index("ix_action_execution_logs_tenant_id", table_name="action_execution_logs")
    op.drop_table("action_execution_logs")
