"""060_lifecycle_v2_history

Lifecycle v2 stage-change history mapped onto the existing pipeline.
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "l1fecyc1ev2"
down_revision: str | Sequence[str] | None = "c0n7ac7memv2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "lifecycle_stage_history",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("from_stage", sa.String(length=120), nullable=True),
        sa.Column("to_stage", sa.String(length=120), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "evidence",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("source", sa.String(length=40), nullable=False, server_default="agent_runtime_v2"),
        sa.Column("trace_id", sa.String(length=120), nullable=True),
        sa.Column("created_by", sa.String(length=120), nullable=True),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_lifecycle_stage_history_tenant_id", "lifecycle_stage_history", ["tenant_id"])
    op.create_index(
        "ix_lifecycle_stage_history_conversation_id",
        "lifecycle_stage_history",
        ["conversation_id"],
    )
    op.create_index("ix_lifecycle_stage_history_to_stage", "lifecycle_stage_history", ["to_stage"])


def downgrade() -> None:
    op.drop_index("ix_lifecycle_stage_history_to_stage", table_name="lifecycle_stage_history")
    op.drop_index(
        "ix_lifecycle_stage_history_conversation_id",
        table_name="lifecycle_stage_history",
    )
    op.drop_index("ix_lifecycle_stage_history_tenant_id", table_name="lifecycle_stage_history")
    op.drop_table("lifecycle_stage_history")
