"""067_product_first_agent_test_runs

Create durable DB-backed Product-First Test Lab run evidence.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "productagents067"
down_revision: str | Sequence[str] | None = "productagents066"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _jsonb(name: str, default: str) -> sa.Column:
    return sa.Column(
        name,
        postgresql.JSONB(astext_type=sa.Text()),
        server_default=sa.text(f"'{default}'::jsonb"),
        nullable=False,
    )


def upgrade() -> None:
    op.create_table(
        "agent_test_runs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("agent_version_id", sa.UUID(), nullable=False),
        sa.Column("test_suite_id", sa.UUID(), nullable=False),
        sa.Column("mode", sa.String(length=40), server_default="no_send", nullable=False),
        sa.Column("status", sa.String(length=40), server_default="running", nullable=False),
        sa.Column("decision", sa.String(length=80), server_default="TEST_LAB_FAILED"),
        _jsonb("scenario_results", "[]"),
        _jsonb("turn_results", "[]"),
        sa.Column("pass_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("fail_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("blocked_count", sa.Integer(), server_default="0", nullable=False),
        _jsonb("trace_ids", "[]"),
        _jsonb("outbox_audit_result", "{}"),
        _jsonb("side_effect_audit_result", "{}"),
        _jsonb("coverage_summary", "{}"),
        sa.Column("review_required", sa.Boolean(), server_default=sa.text("true")),
        sa.Column("created_by_user_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint(
            "mode IN ('no_send', 'parity_check')",
            name="ck_agent_test_runs_mode",
        ),
        sa.CheckConstraint(
            "status IN ('running', 'passed', 'failed', 'blocked')",
            name="ck_agent_test_runs_status",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_version_id"], ["agent_versions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["test_suite_id"], ["agent_test_suites.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_test_runs_agent_version_id", "agent_test_runs", ["agent_version_id"])
    op.create_index("ix_agent_test_runs_tenant_id", "agent_test_runs", ["tenant_id"])
    op.create_index("ix_agent_test_runs_test_suite_id", "agent_test_runs", ["test_suite_id"])


def downgrade() -> None:
    op.drop_table("agent_test_runs")
