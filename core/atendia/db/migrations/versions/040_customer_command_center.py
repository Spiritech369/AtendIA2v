"""040_customer_command_center

Revision ID: f3a4b5c6d7e8
Revises: e2f3a4b5c6d7
Create Date: 2026-05-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f3a4b5c6d7e8"
down_revision: str | Sequence[str] | None = "e2f3a4b5c6d7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "customers", sa.Column("status", sa.String(40), nullable=False, server_default="active")
    )
    op.add_column(
        "customers", sa.Column("stage", sa.String(60), nullable=False, server_default="new")
    )
    op.add_column("customers", sa.Column("source", sa.String(80), nullable=True))
    op.add_column(
        "customers",
        sa.Column(
            "tags",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column("customers", sa.Column("assigned_user_id", sa.UUID(), nullable=True))
    op.add_column(
        "customers", sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "customers", sa.Column("health_score", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column(
        "customers", sa.Column("risk_level", sa.String(20), nullable=False, server_default="low")
    )
    op.add_column(
        "customers",
        sa.Column("sla_status", sa.String(20), nullable=False, server_default="on_track"),
    )
    op.add_column("customers", sa.Column("next_best_action", sa.String(60), nullable=True))
    op.add_column("customers", sa.Column("ai_summary", sa.Text(), nullable=True))
    op.add_column("customers", sa.Column("ai_insight_reason", sa.Text(), nullable=True))
    op.add_column("customers", sa.Column("ai_confidence", sa.Float(), nullable=True))
    op.add_column(
        "customers",
        sa.Column("documents_status", sa.String(30), nullable=False, server_default="missing"),
    )
    op.add_column(
        "customers", sa.Column("last_ai_action_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "customers", sa.Column("last_human_action_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "customers",
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_foreign_key(
        "fk_customers_assigned_user_id_tenant_users",
        "customers",
        "tenant_users",
        ["assigned_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_customers_stage", "customers", ["stage"])
    op.create_index("ix_customers_assigned_user_id", "customers", ["assigned_user_id"])
    op.create_index("ix_customers_last_activity_at", "customers", ["last_activity_at"])
    op.create_index("ix_customers_tenant_stage", "customers", ["tenant_id", "stage"])
    op.create_index("ix_customers_tenant_risk", "customers", ["tenant_id", "risk_level"])

    op.create_table(
        "customer_scores",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("customer_id", sa.UUID(), nullable=False),
        sa.Column("total_score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("intent_score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("activity_score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("documentation_score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("data_quality_score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "conversation_engagement_score", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("stage_progress_score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("abandonment_risk_score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "explanation",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "calculated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_customer_scores_tenant_id", "customer_scores", ["tenant_id"])
    op.create_index("ix_customer_scores_customer_id", "customer_scores", ["customer_id"])
    op.create_index("ix_customer_scores_calculated_at", "customer_scores", ["calculated_at"])

    op.create_table(
        "customer_risks",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("customer_id", sa.UUID(), nullable=False),
        sa.Column("risk_type", sa.String(80), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False, server_default="medium"),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("recommended_action", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_customer_risks_tenant_id", "customer_risks", ["tenant_id"])
    op.create_index("ix_customer_risks_customer_id", "customer_risks", ["customer_id"])
    op.create_index("ix_customer_risks_risk_type", "customer_risks", ["risk_type"])
    op.create_index("ix_customer_risks_status", "customer_risks", ["status"])
    op.create_index("ix_customer_risks_created_at", "customer_risks", ["created_at"])

    op.create_table(
        "customer_next_best_actions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("customer_id", sa.UUID(), nullable=False),
        sa.Column("action_type", sa.String(80), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.7"),
        sa.Column("suggested_message", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_customer_next_best_actions_tenant_id", "customer_next_best_actions", ["tenant_id"]
    )
    op.create_index(
        "ix_customer_next_best_actions_customer_id", "customer_next_best_actions", ["customer_id"]
    )
    op.create_index(
        "ix_customer_next_best_actions_action_type", "customer_next_best_actions", ["action_type"]
    )
    op.create_index(
        "ix_customer_next_best_actions_status", "customer_next_best_actions", ["status"]
    )
    op.create_index(
        "ix_customer_next_best_actions_created_at", "customer_next_best_actions", ["created_at"]
    )

    op.create_table(
        "customer_timeline_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("customer_id", sa.UUID(), nullable=False),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("actor_type", sa.String(30), nullable=False, server_default="system"),
        sa.Column("actor_id", sa.UUID(), nullable=True),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_customer_timeline_events_tenant_id", "customer_timeline_events", ["tenant_id"]
    )
    op.create_index(
        "ix_customer_timeline_events_customer_id", "customer_timeline_events", ["customer_id"]
    )
    op.create_index(
        "ix_customer_timeline_events_event_type", "customer_timeline_events", ["event_type"]
    )
    op.create_index(
        "ix_customer_timeline_events_created_at", "customer_timeline_events", ["created_at"]
    )

    op.create_table(
        "customer_documents",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("customer_id", sa.UUID(), nullable=False),
        sa.Column("document_type", sa.String(80), nullable=False),
        sa.Column("label", sa.String(160), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="missing"),
        sa.Column("file_url", sa.Text(), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_customer_documents_tenant_id", "customer_documents", ["tenant_id"])
    op.create_index("ix_customer_documents_customer_id", "customer_documents", ["customer_id"])
    op.create_index("ix_customer_documents_document_type", "customer_documents", ["document_type"])

    op.create_table(
        "customer_ai_review_items",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("customer_id", sa.UUID(), nullable=False),
        sa.Column("conversation_id", sa.UUID(), nullable=True),
        sa.Column("issue_type", sa.String(80), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False, server_default="medium"),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("ai_summary", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("risky_output_flag", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("human_review_required", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("feedback_status", sa.String(30), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_customer_ai_review_items_tenant_id", "customer_ai_review_items", ["tenant_id"]
    )
    op.create_index(
        "ix_customer_ai_review_items_customer_id", "customer_ai_review_items", ["customer_id"]
    )
    op.create_index(
        "ix_customer_ai_review_items_conversation_id",
        "customer_ai_review_items",
        ["conversation_id"],
    )
    op.create_index(
        "ix_customer_ai_review_items_issue_type", "customer_ai_review_items", ["issue_type"]
    )
    op.create_index("ix_customer_ai_review_items_status", "customer_ai_review_items", ["status"])
    op.create_index(
        "ix_customer_ai_review_items_created_at", "customer_ai_review_items", ["created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_customer_ai_review_items_created_at", table_name="customer_ai_review_items")
    op.drop_index("ix_customer_ai_review_items_status", table_name="customer_ai_review_items")
    op.drop_index("ix_customer_ai_review_items_issue_type", table_name="customer_ai_review_items")
    op.drop_index(
        "ix_customer_ai_review_items_conversation_id", table_name="customer_ai_review_items"
    )
    op.drop_index("ix_customer_ai_review_items_customer_id", table_name="customer_ai_review_items")
    op.drop_index("ix_customer_ai_review_items_tenant_id", table_name="customer_ai_review_items")
    op.drop_table("customer_ai_review_items")

    op.drop_index("ix_customer_documents_document_type", table_name="customer_documents")
    op.drop_index("ix_customer_documents_customer_id", table_name="customer_documents")
    op.drop_index("ix_customer_documents_tenant_id", table_name="customer_documents")
    op.drop_table("customer_documents")

    op.drop_index("ix_customer_timeline_events_created_at", table_name="customer_timeline_events")
    op.drop_index("ix_customer_timeline_events_event_type", table_name="customer_timeline_events")
    op.drop_index("ix_customer_timeline_events_customer_id", table_name="customer_timeline_events")
    op.drop_index("ix_customer_timeline_events_tenant_id", table_name="customer_timeline_events")
    op.drop_table("customer_timeline_events")

    op.drop_index(
        "ix_customer_next_best_actions_created_at", table_name="customer_next_best_actions"
    )
    op.drop_index("ix_customer_next_best_actions_status", table_name="customer_next_best_actions")
    op.drop_index(
        "ix_customer_next_best_actions_action_type", table_name="customer_next_best_actions"
    )
    op.drop_index(
        "ix_customer_next_best_actions_customer_id", table_name="customer_next_best_actions"
    )
    op.drop_index(
        "ix_customer_next_best_actions_tenant_id", table_name="customer_next_best_actions"
    )
    op.drop_table("customer_next_best_actions")

    op.drop_index("ix_customer_risks_created_at", table_name="customer_risks")
    op.drop_index("ix_customer_risks_status", table_name="customer_risks")
    op.drop_index("ix_customer_risks_risk_type", table_name="customer_risks")
    op.drop_index("ix_customer_risks_customer_id", table_name="customer_risks")
    op.drop_index("ix_customer_risks_tenant_id", table_name="customer_risks")
    op.drop_table("customer_risks")

    op.drop_index("ix_customer_scores_calculated_at", table_name="customer_scores")
    op.drop_index("ix_customer_scores_customer_id", table_name="customer_scores")
    op.drop_index("ix_customer_scores_tenant_id", table_name="customer_scores")
    op.drop_table("customer_scores")

    op.drop_index("ix_customers_tenant_risk", table_name="customers")
    op.drop_index("ix_customers_tenant_stage", table_name="customers")
    op.drop_index("ix_customers_last_activity_at", table_name="customers")
    op.drop_index("ix_customers_assigned_user_id", table_name="customers")
    op.drop_index("ix_customers_stage", table_name="customers")
    op.drop_constraint(
        "fk_customers_assigned_user_id_tenant_users", "customers", type_="foreignkey"
    )
    for column in [
        "updated_at",
        "last_human_action_at",
        "last_ai_action_at",
        "documents_status",
        "ai_confidence",
        "ai_insight_reason",
        "ai_summary",
        "next_best_action",
        "sla_status",
        "risk_level",
        "health_score",
        "last_activity_at",
        "assigned_user_id",
        "tags",
        "source",
        "stage",
        "status",
    ]:
        op.drop_column("customers", column)
