"""050_fix_quoted_defaults_class

Revision ID: p2d3e4f5g6h7
Revises: o1c2d3e4f5g6
Create Date: 2026-05-15

Companion to migration 049. Earlier migrations used the
Python-string-with-quotes pattern `server_default="'value'"` for 8
columns — SQLAlchemy passed it through as a SQL string literal, so
Postgres stored the default as `'value'` (with surrounding quotes,
length+2 chars) instead of the bare 4-char `value`. Result: any raw
INSERT that relied on the default landed a quoted literal that
failed the column's CHECK constraint (when one existed) or simply
stored junk (when no constraint guarded the column).

Migration 049 fixed appointments.created_by_type — the one row of
the class that Sprint B.4's test hit. This migration sweeps the
other 7 columns identified via:

  SELECT table_name, column_name, column_default
  FROM information_schema.columns
  WHERE column_default LIKE '%''''''%'

The fix is the same per column: UPDATE rows that carry the bad
literal back to the correct bare value, then ALTER COLUMN SET
DEFAULT with the correct SQL.

ORM writes were unaffected (Python-level model defaults pre-empt
the server default). Production data is expected to be clean —
the UPDATE is a defensive no-op. The DEFAULT fix matters going
forward.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "p2d3e4f5g6h7"
down_revision: str | Sequence[str] | None = "o1c2d3e4f5g6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# (table, column, correct_value)
_FIXES: list[tuple[str, str, str]] = [
    ("agents", "language", "es"),
    ("agents", "role", "custom"),
    ("agents", "tone", "amigable"),
    ("appointments", "status", "scheduled"),
    ("customer_notes", "source", "manual"),
    ("knowledge_documents", "status", "processing"),
    ("workflow_executions", "status", "running"),
]


def upgrade() -> None:
    for table, column, value in _FIXES:
        # The "bad" stored value is the literal `'value'` (4..N chars
        # including the surrounding quotes). In SQL we double each
        # embedded apostrophe, so the comparison literal becomes
        # '''value''' — opening quote, escaped quote, value, escaped
        # quote, closing quote.
        bad_literal_sql = f"'''{value}'''"
        # Defensive UPDATE — normalize any rows that carry the bad value.
        op.execute(
            f"UPDATE {table} SET {column} = '{value}' "
            f"WHERE {column} = {bad_literal_sql}"
        )
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN {column} SET DEFAULT '{value}'"
        )


def downgrade() -> None:
    # Restoring the broken defaults would be perverse. No-op.
    pass
