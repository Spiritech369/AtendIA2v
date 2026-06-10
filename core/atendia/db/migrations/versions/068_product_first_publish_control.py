"""068_product_first_publish_control

Create durable Product-First publish requests for no-send Publish Control.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "productagents068"
down_revision: str | Sequence[str] | None = "productagents067"
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
        "agent_publish_requests",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("agent_version_id", sa.UUID(), nullable=False),
        sa.Column("deployment_id", sa.UUID(), nullable=False),
        sa.Column(
            "requested_state",
            sa.String(length=40),
            server_default="published_no_send",
            nullable=False,
        ),
        sa.Column("status", sa.String(length=40), server_default="draft", nullable=False),
        sa.Column("send_scope", sa.String(length=80), server_default="none", nullable=False),
        sa.Column("channel_scope", sa.String(length=80), nullable=True),
        _jsonb("audience_scope", "{}"),
        _jsonb("test_run_ids", "[]"),
        _jsonb("readiness_snapshot", "{}"),
        _jsonb("blockers", "[]"),
        sa.Column("rollback_version_id", sa.UUID(), nullable=True),
        sa.Column("approval_text", sa.Text(), nullable=True),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column("requested_by_user_id", sa.UUID(), nullable=True),
        sa.Column("approved_by_user_id", sa.UUID(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('draft', 'blocked', 'ready_for_approval', "
            "'approved_no_send', 'rejected')",
            name="ck_agent_publish_requests_status",
        ),
        sa.CheckConstraint(
            "requested_state IN ('published_no_send')",
            name="ck_agent_publish_requests_requested_state",
        ),
        sa.CheckConstraint(
            "send_scope IN ('none', 'test_lab_no_send')",
            name="ck_agent_publish_requests_send_scope",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_version_id"], ["agent_versions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["deployment_id"], ["agent_deployments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["rollback_version_id"], ["agent_versions.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_agent_publish_requests_agent_version_id",
        "agent_publish_requests",
        ["agent_version_id"],
    )
    op.create_index(
        "ix_agent_publish_requests_deployment_id",
        "agent_publish_requests",
        ["deployment_id"],
    )
    op.create_index("ix_agent_publish_requests_tenant_id", "agent_publish_requests", ["tenant_id"])


def downgrade() -> None:
    op.drop_table("agent_publish_requests")
