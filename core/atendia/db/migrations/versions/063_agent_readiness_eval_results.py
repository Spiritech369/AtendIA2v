"""063_agent_readiness_eval_results

Persist Eval Lab readiness results used by AgentRuntime v2 rollout gates.
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "read1nessv2"
down_revision: str | Sequence[str] | None = "0nb04rd1ngv1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_readiness_eval_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("suite_id", sa.String(length=120), nullable=False),
        sa.Column("blueprint_id", sa.String(length=120), nullable=True),
        sa.Column("score", sa.Numeric(5, 4), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("scenario_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "failed_scenarios",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "policy_failures",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["tenant_users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_agent_readiness_eval_results_tenant_agent_created",
        "agent_readiness_eval_results",
        ["tenant_id", "agent_id", "created_at"],
    )
    op.create_index(
        "ix_agent_readiness_eval_results_suite",
        "agent_readiness_eval_results",
        ["suite_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_agent_readiness_eval_results_suite",
        table_name="agent_readiness_eval_results",
    )
    op.drop_index(
        "ix_agent_readiness_eval_results_tenant_agent_created",
        table_name="agent_readiness_eval_results",
    )
    op.drop_table("agent_readiness_eval_results")
