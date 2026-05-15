"""turn_traces tool_cost

Revision ID: c7d3762b4881
Revises: de4463588cea
Create Date: 2026-05-06 02:21:53.731495

Phase 3c.1 — adds `turn_traces.tool_cost_usd numeric(10, 6) nullable`
for tracking per-turn cost of tool calls (initially OpenAI Embeddings
spent inside `lookup_faq` / `search_catalog`).

Mirrors the existing `nlu_cost_usd` / `composer_cost_usd` columns:
same precision/scale, same nullable semantics. Pre-Phase 3c.1 rows
stay NULL; the runner starts populating it once T19 lands.

Decision rationale (design doc decision #12): a separate column
keeps the cost decomposition meaningful in dashboards (NLU vs
Composer vs Tools) instead of co-mingling under nlu_cost_usd.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c7d3762b4881"
down_revision: str | Sequence[str] | None = "de4463588cea"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add tool_cost_usd column."""
    op.add_column(
        "turn_traces",
        sa.Column("tool_cost_usd", sa.Numeric(10, 6), nullable=True),
    )


def downgrade() -> None:
    """Drop the column."""
    op.drop_column("turn_traces", "tool_cost_usd")
