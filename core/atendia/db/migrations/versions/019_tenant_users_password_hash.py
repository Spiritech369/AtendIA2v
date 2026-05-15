"""019_tenant_users_password_hash

Revision ID: b3e91f0c4d28
Revises: 0a8d3f1c5e72
Create Date: 2026-05-07 18:30:00.000000

Phase 4 — adds `tenant_users.password_hash` so operators can log in with
email + password to the dashboard. Bcrypt-hashed (cost 12).

Existing rows: column is NULLABLE — pre-Phase-4 users have no hash yet
and must go through a one-time setup flow (TBD; for now, a superadmin
seed script writes hashes directly). Login rejects rows with NULL hash.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b3e91f0c4d28"
down_revision: str | Sequence[str] | None = "0a8d3f1c5e72"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tenant_users",
        sa.Column("password_hash", sa.String(255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tenant_users", "password_hash")
