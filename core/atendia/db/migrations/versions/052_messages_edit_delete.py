"""052_messages_edit_delete

Revision ID: r4f5g6h7i8j9
Revises: q3e4f5g6h7i8
Create Date: 2026-05-15

C9 — per-message edit/delete. `messages` gains two nullable timestamp
columns:

* edited_at  — set when an operator edits the message text. NULL means
  "never edited"; the frontend shows an "editado" marker when present.
* deleted_at — soft delete. Rows are kept (audit/forensics) but the
  message list filters them out. NULL means "live".

Both nullable so every legacy row stays valid; no backfill.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "r4f5g6h7i8j9"
down_revision: str | Sequence[str] | None = "q3e4f5g6h7i8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "messages",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("messages", "deleted_at")
    op.drop_column("messages", "edited_at")
