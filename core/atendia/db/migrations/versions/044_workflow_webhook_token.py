"""044_workflow_webhook_token

Revision ID: j7e8f9a0b1c2
Revises: i6d7e8f9a0b1
Create Date: 2026-05-13
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "j7e8f9a0b1c2"
down_revision: str | Sequence[str] | None = "i6d7e8f9a0b1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Per-workflow public webhook token. NULL until the operator picks the
    # webhook_received trigger; partial unique index keeps lookup fast and
    # avoids collisions across tenants without polluting non-webhook rows.
    op.add_column(
        "workflows",
        sa.Column("webhook_token", sa.String(48), nullable=True),
    )
    op.create_index(
        "uq_workflows_webhook_token",
        "workflows",
        ["webhook_token"],
        unique=True,
        postgresql_where=sa.text("webhook_token IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_workflows_webhook_token", table_name="workflows")
    op.drop_column("workflows", "webhook_token")
