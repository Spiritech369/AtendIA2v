"""026_v1_parity_roadmap

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-05-08

Adds the v1 parity roadmap schema:
- tenant timezone, notifications, appointments
- knowledge documents/chunks and catalog metadata
- customer score
- agent profiles and conversation assignment
- workflow definitions/executions/cursors/action idempotency
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import HALFVEC  # type: ignore[import-untyped]
from sqlalchemy.dialects import postgresql

revision: str = "c3d4e5f6a7b8"
down_revision: str | Sequence[str] | None = "b2c3d4e5f6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_HNSW_PARAMS: dict[str, int] = {"m": 16, "ef_construction": 64}


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column(
            "timezone",
            sa.String(40),
            nullable=False,
            server_default=sa.text("'America/Mexico_City'"),
        ),
    )
    op.add_column(
        "customers",
        sa.Column("score", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "customer_notes",
        sa.Column("source", sa.String(40), nullable=False, server_default="'manual'"),
    )
    op.add_column(
        "tenant_catalogs",
        sa.Column(
            "tags",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "tenant_catalogs",
        sa.Column("use_count", sa.Integer(), nullable=False, server_default="0"),
    )

    op.create_table(
        "notifications",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("read", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("source_type", sa.String(40), nullable=True),
        sa.Column("source_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["tenant_users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_notifications_user_unread",
        "notifications",
        ["user_id"],
        postgresql_where=sa.text("read = false"),
    )

    op.create_table(
        "appointments",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("customer_id", sa.UUID(), nullable=False),
        sa.Column("conversation_id", sa.UUID(), nullable=True),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("service", sa.String(200), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="'scheduled'"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by_id", sa.UUID(), nullable=True),
        sa.Column("created_by_type", sa.String(10), nullable=False, server_default="'user'"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint(
            "status IN ('scheduled', 'completed', 'cancelled', 'no_show')",
            name="ck_appointments_status",
        ),
        sa.CheckConstraint(
            "created_by_type IN ('user', 'bot')",
            name="ck_appointments_created_by_type",
        ),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_id"], ["tenant_users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_appointments_tenant_date", "appointments", ["tenant_id", "scheduled_at"])
    op.create_index("idx_appointments_customer", "appointments", ["customer_id"])

    op.create_table(
        "knowledge_documents",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("storage_path", sa.String(500), nullable=False),
        sa.Column("category", sa.String(60), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="'processing'"),
        sa.Column("fragment_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "status IN ('processing', 'indexed', 'error')",
            name="ck_knowledge_documents_status",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_knowledge_docs_tenant", "knowledge_documents", ["tenant_id"])

    op.create_table(
        "knowledge_chunks",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("embedding", HALFVEC(3072), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["document_id"], ["knowledge_documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", "chunk_index", name="uq_knowledge_chunks_doc_index"),
    )
    op.create_index("idx_knowledge_chunks_doc", "knowledge_chunks", ["document_id"])
    op.create_index(
        "idx_knowledge_chunks_embedding",
        "knowledge_chunks",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_with=_HNSW_PARAMS,
        postgresql_ops={"embedding": "halfvec_cosine_ops"},
    )

    op.create_table(
        "agents",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("role", sa.String(40), nullable=False, server_default="'custom'"),
        sa.Column("goal", sa.Text(), nullable=True),
        sa.Column("style", sa.String(200), nullable=True),
        sa.Column("tone", sa.String(40), nullable=True, server_default="'amigable'"),
        sa.Column("language", sa.String(20), nullable=True, server_default="'es'"),
        sa.Column("max_sentences", sa.Integer(), nullable=True, server_default="5"),
        sa.Column("no_emoji", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("return_to_flow", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("system_prompt", sa.Text(), nullable=True),
        sa.Column(
            "active_intents",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "extraction_config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "auto_actions",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "knowledge_config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("flow_mode_rules", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
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
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_agents_tenant", "agents", ["tenant_id"])
    op.create_index(
        "idx_agents_default",
        "agents",
        ["tenant_id"],
        unique=True,
        postgresql_where=sa.text("is_default = true"),
    )
    op.add_column(
        "conversations",
        sa.Column("assigned_agent_id", sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        "fk_conversations_assigned_agent_id",
        "conversations",
        "agents",
        ["assigned_agent_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("idx_conversations_assigned_agent_id", "conversations", ["assigned_agent_id"])

    op.create_table(
        "workflows",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("trigger_type", sa.String(60), nullable=False),
        sa.Column(
            "trigger_config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "definition",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text('\'{"nodes":[],"edges":[]}\'::jsonb'),
        ),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("false")),
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
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_workflows_tenant_active",
        "workflows",
        ["tenant_id"],
        postgresql_where=sa.text("active = true"),
    )

    op.create_table(
        "workflow_executions",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("workflow_id", sa.UUID(), nullable=False),
        sa.Column("conversation_id", sa.UUID(), nullable=True),
        sa.Column("customer_id", sa.UUID(), nullable=True),
        sa.Column("trigger_event_id", sa.UUID(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="'running'"),
        sa.Column("current_node_id", sa.String(100), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('running', 'completed', 'failed', 'paused')",
            name="ck_workflow_executions_status",
        ),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["workflow_id"], ["workflows.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_wf_exec_workflow", "workflow_executions", ["workflow_id"])
    op.create_index(
        "idx_wf_exec_idempotent",
        "workflow_executions",
        ["workflow_id", "trigger_event_id"],
        unique=True,
        postgresql_where=sa.text("trigger_event_id IS NOT NULL"),
    )

    op.create_table(
        "workflow_action_runs",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("execution_id", sa.UUID(), nullable=False),
        sa.Column("node_id", sa.String(100), nullable=False),
        sa.Column("action_key", sa.String(160), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["execution_id"], ["workflow_executions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("execution_id", "action_key", name="uq_workflow_action_runs_action"),
    )

    op.create_table(
        "workflow_event_cursors",
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("last_event_id", sa.UUID(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["last_event_id"], ["events.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("tenant_id"),
    )


def downgrade() -> None:
    op.drop_table("workflow_event_cursors")
    op.drop_table("workflow_action_runs")
    op.drop_index("idx_wf_exec_idempotent", table_name="workflow_executions")
    op.drop_index("idx_wf_exec_workflow", table_name="workflow_executions")
    op.drop_table("workflow_executions")
    op.drop_index("idx_workflows_tenant_active", table_name="workflows")
    op.drop_table("workflows")
    op.drop_index("idx_conversations_assigned_agent_id", table_name="conversations")
    op.drop_constraint("fk_conversations_assigned_agent_id", "conversations", type_="foreignkey")
    op.drop_column("conversations", "assigned_agent_id")
    op.drop_index("idx_agents_default", table_name="agents")
    op.drop_index("idx_agents_tenant", table_name="agents")
    op.drop_table("agents")
    op.drop_index("idx_knowledge_chunks_embedding", table_name="knowledge_chunks")
    op.drop_index("idx_knowledge_chunks_doc", table_name="knowledge_chunks")
    op.drop_table("knowledge_chunks")
    op.drop_index("idx_knowledge_docs_tenant", table_name="knowledge_documents")
    op.drop_table("knowledge_documents")
    op.drop_index("idx_appointments_customer", table_name="appointments")
    op.drop_index("idx_appointments_tenant_date", table_name="appointments")
    op.drop_table("appointments")
    op.drop_index("idx_notifications_user_unread", table_name="notifications")
    op.drop_table("notifications")
    op.drop_column("tenant_catalogs", "use_count")
    op.drop_column("tenant_catalogs", "tags")
    op.drop_column("customer_notes", "source")
    op.drop_column("customers", "score")
    op.drop_column("tenants", "timezone")
