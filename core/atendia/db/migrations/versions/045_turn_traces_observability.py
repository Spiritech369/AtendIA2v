"""045_turn_traces_observability

Revision ID: k8f9a0b1c2d3
Revises: j7e8f9a0b1c2
Create Date: 2026-05-14

Adds five additive nullable columns to `turn_traces` so the DebugPanel can
move past heuristic derivations and surface the real router decision, the
raw LLM text, which agent answered, the knowledge evidence that fed the
composer, and the rule-by-rule outcome of the pipeline auto-enter
evaluator.

All columns nullable; legacy rows stay NULL and the runner populates them
going forward. Migrating down drops them.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "k8f9a0b1c2d3"
down_revision: str | Sequence[str] | None = "j7e8f9a0b1c2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Rule id of the flow_mode_rules entry that fired this turn. Stored as
    # a free-form string because tenants can author arbitrary rule ids.
    op.add_column(
        "turn_traces",
        sa.Column("router_trigger", sa.String(80), nullable=True),
    )
    # Raw OpenAI response (the JSON the composer parsed). Helps debug
    # post-processing differences between LLM output and final messages.
    op.add_column(
        "turn_traces",
        sa.Column("raw_llm_response", sa.Text(), nullable=True),
    )
    # Which agent handled the turn. Nullable so the runner stays compatible
    # with tenants that haven't onboarded the agents module yet. ondelete
    # SET NULL — deleting an agent must not destroy its historical traces.
    op.add_column(
        "turn_traces",
        sa.Column("agent_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_turn_traces_agent_id",
        "turn_traces",
        "agents",
        ["agent_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_turn_traces_agent_id"),
        "turn_traces",
        ["agent_id"],
        unique=False,
    )
    # FAQ/catalog hits that fed into the composer's action_payload, with
    # enough metadata for the UI to deep-link back to KB (faq_id /
    # collection_id / sku). Shape:
    #   { "action": "lookup_faq", "hits": [ { source_type, source_id,
    #     collection_id, title, preview, score } ] }
    op.add_column(
        "turn_traces",
        sa.Column("kb_evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    # Per-rule pass/fail for pipeline auto_enter_rules evaluated this turn.
    # Shape: [ { stage_id, condition_index, operator, field, value,
    #            passed } ]
    op.add_column(
        "turn_traces",
        sa.Column("rules_evaluated", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("turn_traces", "rules_evaluated")
    op.drop_column("turn_traces", "kb_evidence")
    op.drop_index(op.f("ix_turn_traces_agent_id"), table_name="turn_traces")
    op.drop_constraint("fk_turn_traces_agent_id", "turn_traces", type_="foreignkey")
    op.drop_column("turn_traces", "agent_id")
    op.drop_column("turn_traces", "raw_llm_response")
    op.drop_column("turn_traces", "router_trigger")
