"""020_turn_traces_bot_paused

Revision ID: c5d72a801fb4
Revises: b3e91f0c4d28
Create Date: 2026-05-07 19:00:00.000000

Phase 4 T24 — adds `turn_traces.bot_paused` so an audit can distinguish
turns where the runner short-circuited because an operator was driving
the conversation. The runner records a minimal trace (turn_number,
inbound_text, bot_paused=True) and returns early.

Existing rows: server_default=false, no backfill needed.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c5d72a801fb4"
down_revision: str | Sequence[str] | None = "b3e91f0c4d28"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "turn_traces",
        sa.Column("bot_paused", sa.Boolean, nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("turn_traces", "bot_paused")
