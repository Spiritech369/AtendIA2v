"""048_turn_traces_composer_provider_cleaned

Revision ID: n1b2c3d4e5f6
Revises: m0a1b2c3d4e5
Create Date: 2026-05-15

Adds two nullable columns to turn_traces for C2 DebugPanel completion:

* composer_provider — which adapter served this turn ("openai",
  "canned", "fallback"). Helps operators distinguish "the LLM said X"
  from "the LLM was unreachable and the canned reply fired".
* inbound_text_cleaned — the normalized text the router actually saw
  for keyword matching (after NFKD diacritic strip + lowercase). The
  NLU and Composer receive the original text; only the rule-based
  router sees the cleaned form. Side-by-side with inbound_text in the
  story lets operators spot cases where the cleanup itself altered
  meaning.

Both nullable so legacy rows stay valid; runner populates them going
forward.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "n1b2c3d4e5f6"
down_revision: str | Sequence[str] | None = "m0a1b2c3d4e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "turn_traces",
        sa.Column("composer_provider", sa.String(20), nullable=True),
    )
    op.add_column(
        "turn_traces",
        sa.Column("inbound_text_cleaned", sa.Text(), nullable=True),
    )
    op.create_check_constraint(
        "ck_turn_traces_composer_provider",
        "turn_traces",
        "composer_provider IS NULL OR composer_provider IN ('openai', 'canned', 'fallback')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_turn_traces_composer_provider", "turn_traces", type_="check")
    op.drop_column("turn_traces", "inbound_text_cleaned")
    op.drop_column("turn_traces", "composer_provider")
