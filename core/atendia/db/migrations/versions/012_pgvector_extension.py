"""create pgvector extension

Revision ID: c9c3bfbc5157
Revises: 4329f44c0243
Create Date: 2026-05-06 02:15:28.860044

Phase 3c.1 — enables semantic search over `tenant_catalogs` and
`tenant_faqs` via OpenAI text-embedding-3-large (3072 dims).

Idempotent: `IF NOT EXISTS` covers cases where the extension was
created manually before this migration ran.

Downgrade is a no-op: dropping the extension would cascade into any
column declared with the `vector` type, which we don't want during
a migration rollback. Operators should drop the columns first
(migrations 013+) and only then drop the extension manually.
"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c9c3bfbc5157'
down_revision: str | Sequence[str] | None = '4329f44c0243'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Enable the pgvector extension."""
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")


def downgrade() -> None:
    """No-op: see module docstring."""
    pass
