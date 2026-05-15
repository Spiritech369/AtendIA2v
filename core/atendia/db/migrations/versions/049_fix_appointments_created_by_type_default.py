"""049_fix_appointments_created_by_type_default

Revision ID: o1c2d3e4f5g6
Revises: n1b2c3d4e5f6
Create Date: 2026-05-15

D9 — Migration 026 emitted DEFAULT '''user''' (three single quotes,
SQLAlchemy interpreted the Python string "'user'" literally so the
generated SQL was DEFAULT '''user''') for appointments.created_by_type.
Postgres stored the default as the literal 'user' (4 chars including
quotes), which fails the CHECK constraint
  created_by_type IN ('user', 'bot', 'ai')
on any raw INSERT that omits the column.

The bug was masked in production because the SQLAlchemy model has
default="user" at the Python level — the ORM substitutes the value
before the INSERT runs. Tests that did raw INSERT (Sprint B.4
reminder worker test) hit the bug and worked around it by passing
created_by_type='user' explicitly.

This migration restores the correct default. UPDATE is a defensive
no-op — no production row is expected to carry the quoted literal,
but if any did slip through they get normalized.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "o1c2d3e4f5g6"
down_revision: str | Sequence[str] | None = "n1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # First, normalize any rows that snuck in with the bad literal.
    op.execute(
        "UPDATE appointments SET created_by_type = 'user' WHERE created_by_type = '''user'''"
    )
    # Then fix the column default so future raw INSERTs work.
    op.execute("ALTER TABLE appointments ALTER COLUMN created_by_type SET DEFAULT 'user'")


def downgrade() -> None:
    # Reinstating the broken default would be perverse — leave the
    # correct one in place. Downgrades from this migration are
    # functionally a no-op.
    pass
