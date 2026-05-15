"""015_turn_traces_flow_mode_vision

Revision ID: 68e0a0c407f9
Revises: c7d3762b4881
Create Date: 2026-05-06 19:44:11.284294

Phase 3c.2 — adds:
  * `turn_traces.flow_mode VARCHAR(20)` — modo elegido por el router este turno
  * `turn_traces.vision_cost_usd NUMERIC(10, 6)` — Vision API spent this turn
  * `turn_traces.vision_latency_ms INTEGER` — Vision API latency this turn

`flow_mode` is set per-turn by the deterministic router; one of:
PLAN/SALES/DOC/OBSTACLE/RETENTION/SUPPORT (NULL on legacy rows).

`vision_cost_usd` is separate from `tool_cost_usd` (which already tracks
embeddings) so dashboards can distinguish embedding vs vision spend.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "68e0a0c407f9"
down_revision: str | Sequence[str] | None = "c7d3762b4881"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add flow_mode + vision_cost_usd + vision_latency_ms columns."""
    op.add_column(
        "turn_traces",
        sa.Column("flow_mode", sa.String(20), nullable=True),
    )
    op.add_column(
        "turn_traces",
        sa.Column("vision_cost_usd", sa.Numeric(10, 6), nullable=True),
    )
    op.add_column(
        "turn_traces",
        sa.Column("vision_latency_ms", sa.Integer, nullable=True),
    )


def downgrade() -> None:
    """Drop the three columns in reverse order."""
    op.drop_column("turn_traces", "vision_latency_ms")
    op.drop_column("turn_traces", "vision_cost_usd")
    op.drop_column("turn_traces", "flow_mode")
