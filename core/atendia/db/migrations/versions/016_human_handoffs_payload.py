"""016_human_handoffs_payload

Revision ID: 7a1f8c5e2b03
Revises: 68e0a0c407f9
Create Date: 2026-05-07 10:00:00.000000

Phase 3c.2 — T24:
  * `human_handoffs.payload JSONB` — structured HandoffSummary so the
    operator dashboard can render context (nombre, plan, docs received,
    last inbound, suggested next action) without parsing free-text reasons.

Existing rows get NULL — the dashboard already tolerates that path
(legacy handoffs were reason-only).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "7a1f8c5e2b03"
down_revision: str | Sequence[str] | None = "68e0a0c407f9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "human_handoffs",
        sa.Column("payload", postgresql.JSONB, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("human_handoffs", "payload")
