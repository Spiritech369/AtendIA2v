"""017_followups_scheduling_columns

Revision ID: 8c2e4d61f9a3
Revises: 7a1f8c5e2b03
Create Date: 2026-05-07 14:00:00.000000

Phase 3d v1 — extends `followups_scheduled` so the cron worker can run safely
under load:
  * `kind: VARCHAR(40)` — '3h_silence', '12h_silence', etc. — drives which
    body to render at fire time. The pre-existing `template_id` slot stays
    (NULL when sending plain text within 24h window).
  * `enqueued_at: TIMESTAMP` — set BEFORE arq enqueue. A row with
    enqueued_at IS NOT NULL is "in flight" and won't be re-picked even if
    the worker dies before status='sent'. Idempotency on restarts.
  * `cancelled_at: TIMESTAMP` — set when an inbound message arrives. The
    worker re-checks this inside the SELECT FOR UPDATE txn before
    enqueueing.
  * `context: JSONB` — extracted_data snapshot at scheduling time. Audit
    trail only; the cron worker renders bodies from CURRENT extracted_data
    so a customer who set their plan_credito between schedule and fire
    sees the up-to-date plan.

Plus:
  * `tenants.followups_enabled BOOLEAN DEFAULT TRUE` — cheap kill-switch
    for an angry tenant. The cron query joins and filters on this.

Existing rows: kind/enqueued_at/cancelled_at/context = NULL; tenants get
TRUE by default. No backfill required.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "8c2e4d61f9a3"
down_revision: str | Sequence[str] | None = "7a1f8c5e2b03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "followups_scheduled",
        sa.Column("kind", sa.String(40), nullable=True),
    )
    op.add_column(
        "followups_scheduled",
        sa.Column("enqueued_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "followups_scheduled",
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "followups_scheduled",
        sa.Column("context", postgresql.JSONB, nullable=True),
    )
    # Composite index drives the cron worker's hot-path query:
    # WHERE status='pending' AND cancelled_at IS NULL AND enqueued_at IS NULL
    #   AND run_at <= NOW()
    op.create_index(
        "ix_followups_scheduled_due",
        "followups_scheduled",
        ["status", "run_at"],
    )
    op.add_column(
        "tenants",
        sa.Column("followups_enabled", sa.Boolean, nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    op.drop_column("tenants", "followups_enabled")
    op.drop_index("ix_followups_scheduled_due", table_name="followups_scheduled")
    op.drop_column("followups_scheduled", "context")
    op.drop_column("followups_scheduled", "cancelled_at")
    op.drop_column("followups_scheduled", "enqueued_at")
    op.drop_column("followups_scheduled", "kind")
