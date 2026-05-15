"""037_workflow_operations_center

Revision ID: c0d1e2f3a4b5
Revises: b4eed6306737
Create Date: 2026-05-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c0d1e2f3a4b5"
down_revision: str | Sequence[str] | None = "b4eed6306737"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workflow_versions",
        sa.Column("id", sa.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "workflow_id",
            sa.UUID(),
            sa.ForeignKey("workflows.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column(
            "definition",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("change_summary", sa.Text()),
        sa.Column("editor_name", sa.String(160)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("workflow_id", "version_number", name="uq_workflow_versions_number"),
    )
    op.create_index("ix_workflow_versions_workflow_id", "workflow_versions", ["workflow_id"])

    op.create_table(
        "workflow_execution_steps",
        sa.Column("id", sa.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "execution_id",
            sa.UUID(),
            sa.ForeignKey("workflow_executions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("node_id", sa.String(100), nullable=False),
        sa.Column("node_title", sa.String(200)),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column(
            "input_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "output_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("error", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("duration_ms", sa.Integer()),
    )
    op.create_index(
        "ix_workflow_execution_steps_execution_id", "workflow_execution_steps", ["execution_id"]
    )

    op.create_table(
        "workflow_variables",
        sa.Column("id", sa.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "workflow_id",
            sa.UUID(),
            sa.ForeignKey("workflows.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("created_in_node_id", sa.String(100)),
        sa.Column(
            "used_in_nodes",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("last_value", sa.String(300)),
        sa.Column("status", sa.String(20), nullable=False, server_default="ok"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("workflow_id", "name", name="uq_workflow_variables_name"),
    )
    op.create_index("ix_workflow_variables_workflow_id", "workflow_variables", ["workflow_id"])

    op.create_table(
        "workflow_dependencies",
        sa.Column("id", sa.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "workflow_id",
            sa.UUID(),
            sa.ForeignKey("workflows.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("dependency_type", sa.String(40), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="ok"),
        sa.Column(
            "details",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_workflow_dependencies_workflow_id", "workflow_dependencies", ["workflow_id"]
    )

    op.create_table(
        "whatsapp_templates",
        sa.Column("id", sa.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "tenant_id", sa.UUID(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("category", sa.String(40), nullable=False, server_default="utility"),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("language", sa.String(12), nullable=False, server_default="es_MX"),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "variables",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("tenant_id", "name", name="uq_whatsapp_templates_name"),
    )
    op.create_index("ix_whatsapp_templates_tenant_id", "whatsapp_templates", ["tenant_id"])

    op.create_table(
        "ai_agents",
        sa.Column("id", sa.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "tenant_id", sa.UUID(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("role", sa.String(40), nullable=False, server_default="sales"),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column(
            "config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("tenant_id", "name", name="uq_ai_agents_name"),
    )
    op.create_index("ix_ai_agents_tenant_id", "ai_agents", ["tenant_id"])

    op.create_table(
        "knowledge_base_sources",
        sa.Column("id", sa.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "tenant_id", sa.UUID(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("source_type", sa.String(40), nullable=False, server_default="document"),
        sa.Column("status", sa.String(20), nullable=False, server_default="indexed"),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_knowledge_base_sources_tenant_id", "knowledge_base_sources", ["tenant_id"])

    op.create_table(
        "advisor_pools",
        sa.Column("id", sa.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "tenant_id", sa.UUID(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("strategy", sa.String(40), nullable=False, server_default="round_robin"),
        sa.Column(
            "advisor_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_advisor_pools_tenant_id", "advisor_pools", ["tenant_id"])

    op.create_table(
        "business_hours_rules",
        sa.Column("id", sa.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "tenant_id", sa.UUID(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("timezone", sa.String(40), nullable=False, server_default="America/Mexico_City"),
        sa.Column(
            "schedule",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_business_hours_rules_tenant_id", "business_hours_rules", ["tenant_id"])

    op.create_table(
        "safety_rules",
        sa.Column("id", sa.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "tenant_id", sa.UUID(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("workflow_id", sa.UUID(), sa.ForeignKey("workflows.id", ondelete="CASCADE")),
        sa.Column("key", sa.String(80), nullable=False),
        sa.Column("label", sa.String(200), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_safety_rules_tenant_id", "safety_rules", ["tenant_id"])
    op.create_index("ix_safety_rules_workflow_id", "safety_rules", ["workflow_id"])


def downgrade() -> None:
    op.drop_index("ix_safety_rules_workflow_id", table_name="safety_rules")
    op.drop_index("ix_safety_rules_tenant_id", table_name="safety_rules")
    op.drop_table("safety_rules")
    op.drop_index("ix_business_hours_rules_tenant_id", table_name="business_hours_rules")
    op.drop_table("business_hours_rules")
    op.drop_index("ix_advisor_pools_tenant_id", table_name="advisor_pools")
    op.drop_table("advisor_pools")
    op.drop_index("ix_knowledge_base_sources_tenant_id", table_name="knowledge_base_sources")
    op.drop_table("knowledge_base_sources")
    op.drop_index("ix_ai_agents_tenant_id", table_name="ai_agents")
    op.drop_table("ai_agents")
    op.drop_index("ix_whatsapp_templates_tenant_id", table_name="whatsapp_templates")
    op.drop_table("whatsapp_templates")
    op.drop_index("ix_workflow_dependencies_workflow_id", table_name="workflow_dependencies")
    op.drop_table("workflow_dependencies")
    op.drop_index("ix_workflow_variables_workflow_id", table_name="workflow_variables")
    op.drop_table("workflow_variables")
    op.drop_index("ix_workflow_execution_steps_execution_id", table_name="workflow_execution_steps")
    op.drop_table("workflow_execution_steps")
    op.drop_index("ix_workflow_versions_workflow_id", table_name="workflow_versions")
    op.drop_table("workflow_versions")
