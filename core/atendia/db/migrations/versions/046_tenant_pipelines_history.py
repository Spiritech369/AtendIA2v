"""046_tenant_pipelines_history

Revision ID: l9a0b1c2d3e4
Revises: k8f9a0b1c2d3
Create Date: 2026-05-14

Adds `tenant_pipelines.history` (JSONB) so each save captures a snapshot
of the previous definition. Powers the P1 version-rollback UI: list past
versions, diff against current, restore a chosen version with confirmation.

Why inline JSONB and not a separate table:
* tenant_pipelines is already single-row-per-tenant since the cleanup of
  the multi-row design — adding a sibling table just to track snapshots
  would re-introduce the "audit drift" that motivated the cleanup;
* history is capped at the last 10 snapshots in the route, so the
  column stays small enough to keep the row cheap (TOAST kicks in past
  ~2KB anyway);
* mirrors the agents pattern (ops_config["versions"][...].snapshot).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "l9a0b1c2d3e4"
down_revision: str | Sequence[str] | None = "k8f9a0b1c2d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tenant_pipelines",
        sa.Column(
            "history",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("tenant_pipelines", "history")
