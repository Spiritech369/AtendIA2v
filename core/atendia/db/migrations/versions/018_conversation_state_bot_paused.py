"""018_conversation_state_bot_paused

Revision ID: 0a8d3f1c5e72
Revises: 8c2e4d61f9a3
Create Date: 2026-05-07 18:00:00.000000

Phase 4 — adds `conversation_state.bot_paused` so an operator can take over
a conversation from the dashboard. When True, the runner short-circuits
without invoking NLU/composer/tools; inbound messages are still recorded but
the bot stays silent. The operator's outbound messages bypass the runner and
go straight to the queue (see `POST /api/v1/conversations/:cid/intervene`).

Resume-bot path flips the flag back to False; next inbound runs normally.

Existing rows: server_default=false so all current conversations remain
bot-driven. No backfill required.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0a8d3f1c5e72"
down_revision: str | Sequence[str] | None = "8c2e4d61f9a3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "conversation_state",
        sa.Column("bot_paused", sa.Boolean, nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("conversation_state", "bot_paused")
