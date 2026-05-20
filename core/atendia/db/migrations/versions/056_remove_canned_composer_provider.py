"""056_remove_canned_composer_provider

Revision ID: v8j9k0l1m2n3
Revises: u7i8j9k0l1m2
Create Date: 2026-05-20

Composer runtime is OpenAI-only. Legacy traces may still show "fallback",
but new data must not persist "canned" as a composer provider.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "v8j9k0l1m2n3"
down_revision: str | Sequence[str] | None = "u7i8j9k0l1m2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_turn_traces_composer_provider", "turn_traces", type_="check")
    op.execute("UPDATE turn_traces SET composer_provider = NULL WHERE composer_provider = 'canned'")
    op.create_check_constraint(
        "ck_turn_traces_composer_provider",
        "turn_traces",
        "composer_provider IS NULL OR composer_provider IN ('openai', 'fallback')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_turn_traces_composer_provider", "turn_traces", type_="check")
    op.create_check_constraint(
        "ck_turn_traces_composer_provider",
        "turn_traces",
        "composer_provider IS NULL OR composer_provider IN ('openai', 'fallback')",
    )
