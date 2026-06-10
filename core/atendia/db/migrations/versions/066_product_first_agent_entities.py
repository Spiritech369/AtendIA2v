"""066_product_first_agent_entities

Create tenant-scoped Product-First agent control-plane entities.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "productagents066"
down_revision: str | Sequence[str] | None = "businesseventledger065"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _jsonb(default: str = "{}") -> sa.Column:
    return sa.Column(
        postgresql.JSONB(astext_type=sa.Text()),
        server_default=sa.text(f"'{default}'::jsonb"),
        nullable=False,
    )


def upgrade() -> None:
    op.create_table(
        "agent_versions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), server_default="draft", nullable=False),
        sa.Column("is_immutable", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("role", sa.String(length=80), nullable=True),
        sa.Column("tone", sa.String(length=80), nullable=True),
        sa.Column("language", sa.String(length=20), nullable=True),
        sa.Column("instructions", sa.Text(), nullable=True),
        sa.Column(
            "prompt_blocks",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "knowledge_policy",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "tool_policy",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "action_policy",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "field_policy",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "workflow_policy",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "safety_policy",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "test_policy",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("change_summary", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.UUID(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('draft', 'published', 'archived')",
            name="ck_agent_versions_status",
        ),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "agent_id",
            "version_number",
            name="uq_agent_versions_tenant_agent_number",
        ),
    )
    op.create_index("ix_agent_versions_agent_id", "agent_versions", ["agent_id"])
    op.create_index("ix_agent_versions_tenant_id", "agent_versions", ["tenant_id"])

    op.create_table(
        "agent_deployments",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("active_version_id", sa.UUID(), nullable=True),
        sa.Column("rollback_version_id", sa.UUID(), nullable=True),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("channel", sa.String(length=40), server_default="test_lab", nullable=False),
        sa.Column("environment", sa.String(length=40), server_default="no_send", nullable=False),
        sa.Column("publish_state", sa.String(length=40), server_default="draft", nullable=False),
        sa.Column("runtime_mode", sa.String(length=80), server_default="no_send", nullable=False),
        sa.Column("send_scope", sa.String(length=80), server_default="none", nullable=False),
        sa.Column("send_enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("outbox_enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "live_send_enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column(
            "single_contact_smoke_enabled",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("actions_enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "workflow_events_enabled",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "workflow_side_effects_enabled",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("canary_enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "open_production_enabled",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("created_by_user_id", sa.UUID(), nullable=True),
        sa.Column("approved_by_user_id", sa.UUID(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint(
            "publish_state IN ("
            "'draft', 'test_required', 'test_passed', 'ready_for_approval', "
            "'published_no_send', 'paused', 'rollback_required', 'rolled_back', 'archived'"
            ")",
            name="ck_agent_deployments_publish_state",
        ),
        sa.ForeignKeyConstraint(["active_version_id"], ["agent_versions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["rollback_version_id"], ["agent_versions.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "agent_id",
            "channel",
            "environment",
            name="uq_agent_deployments_scope",
        ),
    )
    op.create_index(
        "ix_agent_deployments_active_version_id", "agent_deployments", ["active_version_id"]
    )
    op.create_index("ix_agent_deployments_agent_id", "agent_deployments", ["agent_id"])
    op.create_index("ix_agent_deployments_tenant_id", "agent_deployments", ["tenant_id"])

    op.create_table(
        "agent_knowledge_source_bindings",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("agent_version_id", sa.UUID(), nullable=False),
        sa.Column("knowledge_source_id", sa.UUID(), nullable=False),
        sa.Column("binding_mode", sa.String(length=40), server_default="read", nullable=False),
        sa.Column("required", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("priority", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["agent_version_id"], ["agent_versions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["knowledge_source_id"], ["knowledge_sources.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "agent_version_id",
            "knowledge_source_id",
            name="uq_agent_knowledge_source_bindings_source",
        ),
    )
    op.create_index(
        "ix_agent_knowledge_source_bindings_agent_version_id",
        "agent_knowledge_source_bindings",
        ["agent_version_id"],
    )
    op.create_index(
        "ix_agent_knowledge_source_bindings_knowledge_source_id",
        "agent_knowledge_source_bindings",
        ["knowledge_source_id"],
    )
    op.create_index(
        "ix_agent_knowledge_source_bindings_tenant_id",
        "agent_knowledge_source_bindings",
        ["tenant_id"],
    )

    op.create_table(
        "agent_tool_bindings",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("agent_version_id", sa.UUID(), nullable=False),
        sa.Column("tool_name", sa.String(length=120), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("required", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "input_schema",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "output_schema",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("timeout_ms", sa.Integer(), nullable=True),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["agent_version_id"], ["agent_versions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "agent_version_id",
            "tool_name",
            name="uq_agent_tool_bindings_tool",
        ),
    )
    op.create_index(
        "ix_agent_tool_bindings_agent_version_id", "agent_tool_bindings", ["agent_version_id"]
    )
    op.create_index("ix_agent_tool_bindings_tenant_id", "agent_tool_bindings", ["tenant_id"])

    op.create_table(
        "agent_action_bindings",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("agent_version_id", sa.UUID(), nullable=False),
        sa.Column("action_key", sa.String(length=160), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "execution_mode", sa.String(length=40), server_default="disabled", nullable=False
        ),
        sa.Column(
            "approval_required", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column(
            "permissions",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "input_schema",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "output_schema",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint(
            "execution_mode IN ('disabled', 'dry_run_only', 'approval_required')",
            name="ck_agent_action_bindings_execution_mode",
        ),
        sa.ForeignKeyConstraint(["agent_version_id"], ["agent_versions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "agent_version_id",
            "action_key",
            name="uq_agent_action_bindings_action",
        ),
    )
    op.create_index(
        "ix_agent_action_bindings_agent_version_id", "agent_action_bindings", ["agent_version_id"]
    )
    op.create_index("ix_agent_action_bindings_tenant_id", "agent_action_bindings", ["tenant_id"])

    op.create_table(
        "agent_field_permissions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("agent_version_id", sa.UUID(), nullable=False),
        sa.Column("field_key", sa.String(length=160), nullable=False),
        sa.Column("can_read", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("can_write", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "evidence_required", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column(
            "write_policy",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["agent_version_id"], ["agent_versions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "agent_version_id",
            "field_key",
            name="uq_agent_field_permissions_field",
        ),
    )
    op.create_index(
        "ix_agent_field_permissions_agent_version_id",
        "agent_field_permissions",
        ["agent_version_id"],
    )
    op.create_index(
        "ix_agent_field_permissions_tenant_id", "agent_field_permissions", ["tenant_id"]
    )

    op.create_table(
        "agent_workflow_bindings",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("agent_version_id", sa.UUID(), nullable=False),
        sa.Column("workflow_id", sa.UUID(), nullable=False),
        sa.Column("event_type", sa.String(length=120), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "execution_mode", sa.String(length=40), server_default="disabled", nullable=False
        ),
        sa.Column(
            "side_effects_allowed", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column(
            "customer_visible_output_allowed",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint(
            "execution_mode IN ('disabled', 'dry_run_only', 'approval_required')",
            name="ck_agent_workflow_bindings_execution_mode",
        ),
        sa.ForeignKeyConstraint(["agent_version_id"], ["agent_versions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workflow_id"], ["workflows.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "agent_version_id",
            "workflow_id",
            "event_type",
            name="uq_agent_workflow_bindings_workflow_event",
        ),
    )
    op.create_index(
        "ix_agent_workflow_bindings_agent_version_id",
        "agent_workflow_bindings",
        ["agent_version_id"],
    )
    op.create_index(
        "ix_agent_workflow_bindings_tenant_id", "agent_workflow_bindings", ["tenant_id"]
    )
    op.create_index(
        "ix_agent_workflow_bindings_workflow_id", "agent_workflow_bindings", ["workflow_id"]
    )

    op.create_table(
        "agent_test_suites",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("agent_version_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("mode", sa.String(length=40), server_default="no_send", nullable=False),
        sa.Column("status", sa.String(length=40), server_default="draft", nullable=False),
        sa.Column("last_run_id", sa.UUID(), nullable=True),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["agent_version_id"], ["agent_versions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_agent_test_suites_agent_version_id", "agent_test_suites", ["agent_version_id"]
    )
    op.create_index("ix_agent_test_suites_tenant_id", "agent_test_suites", ["tenant_id"])

    op.create_table(
        "agent_test_scenarios",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("test_suite_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column(
            "turns",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "expected",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=40), server_default="draft", nullable=False),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["test_suite_id"], ["agent_test_suites.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_test_scenarios_tenant_id", "agent_test_scenarios", ["tenant_id"])
    op.create_index(
        "ix_agent_test_scenarios_test_suite_id", "agent_test_scenarios", ["test_suite_id"]
    )

    op.create_table(
        "agent_publish_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("deployment_id", sa.UUID(), nullable=False),
        sa.Column("agent_version_id", sa.UUID(), nullable=True),
        sa.Column("from_state", sa.String(length=40), nullable=True),
        sa.Column("to_state", sa.String(length=40), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("actor_user_id", sa.UUID(), nullable=True),
        sa.Column(
            "safety_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["agent_version_id"], ["agent_versions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["deployment_id"], ["agent_deployments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_agent_publish_events_deployment_id", "agent_publish_events", ["deployment_id"]
    )
    op.create_index("ix_agent_publish_events_tenant_id", "agent_publish_events", ["tenant_id"])


def downgrade() -> None:
    op.drop_table("agent_publish_events")
    op.drop_table("agent_test_scenarios")
    op.drop_table("agent_test_suites")
    op.drop_table("agent_workflow_bindings")
    op.drop_table("agent_field_permissions")
    op.drop_table("agent_action_bindings")
    op.drop_table("agent_tool_bindings")
    op.drop_table("agent_knowledge_source_bindings")
    op.drop_table("agent_deployments")
    op.drop_table("agent_versions")
