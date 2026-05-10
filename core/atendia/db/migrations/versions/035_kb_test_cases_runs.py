"""035_kb_test_cases_runs

Revision ID: 5ab7479a44a0
Revises: e133dc8ec51b
Create Date: 2026-05-10
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "5ab7479a44a0"
down_revision: str | Sequence[str] | None = "e133dc8ec51b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "kb_test_cases",
        sa.Column("id", sa.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", sa.UUID(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("user_query", sa.Text(), nullable=False),
        sa.Column(
            "expected_sources",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "expected_keywords",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("ARRAY[]::text[]"),
        ),
        sa.Column(
            "forbidden_phrases",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("ARRAY[]::text[]"),
        ),
        sa.Column("agent", sa.String(40), nullable=False),
        sa.Column(
            "required_customer_fields",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("ARRAY[]::text[]"),
        ),
        sa.Column("expected_action", sa.String(20), nullable=False, server_default="answer"),
        sa.Column("minimum_score", sa.Float(), nullable=False, server_default="0.7"),
        sa.Column("is_critical", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_by", sa.UUID()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "kb_test_runs",
        sa.Column("id", sa.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", sa.UUID(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("test_case_id", sa.UUID(), sa.ForeignKey("kb_test_cases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column(
            "retrieved_sources",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("generated_answer", sa.Text()),
        sa.Column(
            "diff_vs_expected",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("duration_ms", sa.Integer()),
        sa.Column(
            "failure_reasons",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("ARRAY[]::text[]"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_kb_test_runs_run", "kb_test_runs", ["tenant_id", "run_id"])


def downgrade() -> None:
    op.drop_index("ix_kb_test_runs_run", table_name="kb_test_runs")
    op.drop_table("kb_test_runs")
    op.drop_table("kb_test_cases")
