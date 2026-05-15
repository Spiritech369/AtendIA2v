"""034_kb_conflicts_unanswered

Revision ID: e133dc8ec51b
Revises: dafa3c47b0bb
Create Date: 2026-05-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e133dc8ec51b"
down_revision: str | Sequence[str] | None = "dafa3c47b0bb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "kb_conflicts",
        sa.Column("id", sa.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "tenant_id", sa.UUID(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("detection_type", sa.String(30), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False, server_default="medium"),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("entity_a_type", sa.String(20), nullable=False),
        sa.Column("entity_a_id", sa.UUID(), nullable=False),
        sa.Column("entity_a_excerpt", sa.Text()),
        sa.Column("entity_b_type", sa.String(20), nullable=False),
        sa.Column("entity_b_id", sa.UUID(), nullable=False),
        sa.Column("entity_b_excerpt", sa.Text()),
        sa.Column("suggested_priority", sa.Text()),
        sa.Column("assigned_to", sa.UUID()),
        sa.Column("resolved_by", sa.UUID()),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("resolution_action", sa.String(40)),
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
    )
    op.create_index("ix_kb_conflicts_status", "kb_conflicts", ["tenant_id", "status"])

    op.create_table(
        "kb_unanswered_questions",
        sa.Column("id", sa.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "tenant_id", sa.UUID(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("query_normalized", sa.Text(), nullable=False),
        sa.Column("agent", sa.String(40)),
        sa.Column("conversation_id", sa.UUID()),
        sa.Column("top_score", sa.Float()),
        sa.Column("llm_confidence", sa.String(20)),
        sa.Column("escalation_reason", sa.Text()),
        sa.Column(
            "failed_chunks",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("suggested_answer", sa.Text()),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("assigned_to", sa.UUID()),
        sa.Column("linked_faq_id", sa.UUID()),
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
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "ix_kb_unanswered_status",
        "kb_unanswered_questions",
        ["tenant_id", "status", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_kb_unanswered_status", table_name="kb_unanswered_questions")
    op.drop_table("kb_unanswered_questions")
    op.drop_index("ix_kb_conflicts_status", table_name="kb_conflicts")
    op.drop_table("kb_conflicts")
