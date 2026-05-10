"""036_kb_health_perms_priority_safe — last migration of Phase 1

Revision ID: b4eed6306737
Revises: 5ab7479a44a0
Create Date: 2026-05-10
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b4eed6306737"
down_revision: str | Sequence[str] | None = "5ab7479a44a0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_DEFAULT_FALLBACK_ES_MX = (
    "Déjame validarlo con un asesor para darte la información correcta."
)


def upgrade() -> None:
    op.create_table(
        "kb_health_snapshots",
        sa.Column("id", sa.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", sa.UUID(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("snapshot_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column(
            "score_components",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "main_risks",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "suggested_actions",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "per_collection_scores",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.create_index(
        "ix_kb_health_tenant_at",
        "kb_health_snapshots",
        ["tenant_id", sa.text("snapshot_at DESC")],
    )

    op.create_table(
        "kb_agent_permissions",
        sa.Column("id", sa.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", sa.UUID(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agent", sa.String(40), nullable=False),
        sa.Column(
            "allowed_source_types",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("ARRAY[]::text[]"),
        ),
        sa.Column(
            "allowed_collection_slugs",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("ARRAY[]::text[]"),
        ),
        sa.Column("min_score", sa.Float(), nullable=False, server_default="0.7"),
        sa.Column("can_quote_prices", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("can_quote_stock", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "required_customer_fields",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("ARRAY[]::text[]"),
        ),
        sa.Column("escalate_on_conflict", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("fallback_message", sa.Text()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_by", sa.UUID()),
    )
    op.create_index("uq_kb_agent_perms", "kb_agent_permissions", ["tenant_id", "agent"], unique=True)

    op.create_table(
        "kb_source_priority_rules",
        sa.Column("id", sa.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", sa.UUID(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agent", sa.String(40)),
        sa.Column("source_type", sa.String(20), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("minimum_score", sa.Float(), nullable=False, server_default="0.7"),
        sa.Column("allow_synthesis", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("allow_direct_answer", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("escalation_required_when_conflict", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_kb_priority_tenant_agent", "kb_source_priority_rules", ["tenant_id", "agent"])

    op.create_table(
        "kb_safe_answer_settings",
        sa.Column("tenant_id", sa.UUID(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("min_score_to_answer", sa.Float(), nullable=False, server_default="0.7"),
        sa.Column("escalate_on_conflict", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("block_invented_prices", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("block_invented_stock", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "risky_phrases",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "default_fallback_message",
            sa.Text(),
            nullable=False,
            server_default=_DEFAULT_FALLBACK_ES_MX,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_by", sa.UUID()),
    )


def downgrade() -> None:
    op.drop_table("kb_safe_answer_settings")
    op.drop_index("ix_kb_priority_tenant_agent", table_name="kb_source_priority_rules")
    op.drop_table("kb_source_priority_rules")
    op.drop_index("uq_kb_agent_perms", table_name="kb_agent_permissions")
    op.drop_table("kb_agent_permissions")
    op.drop_index("ix_kb_health_tenant_at", table_name="kb_health_snapshots")
    op.drop_table("kb_health_snapshots")
