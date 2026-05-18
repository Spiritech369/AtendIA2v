"""054_seed_unassign_system_user

Revision ID: t6h7i8j9k0l1
Revises: s5g6h7i8j9k0
Create Date: 2026-05-17

Seed a tenant-scoped sentinel user used by prompt references such as
``@Desasignar``. The runtime meaning is "clear assignment"; this row
exists so every tenant has a consistent registry entry without creating
a login-capable operator.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "t6h7i8j9k0l1"
down_revision: str | Sequence[str] | None = "s5g6h7i8j9k0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


SYSTEM_UNASSIGN_EMAIL = "desasignar@system.local"


def upgrade() -> None:
    op.get_bind().execute(
        sa.text(
            """
            INSERT INTO tenant_users (id, tenant_id, email, role, password_hash)
            SELECT gen_random_uuid(), t.id, CAST(:email AS varchar), 'operator', NULL
            FROM tenants t
            WHERE NOT EXISTS (
                SELECT 1
                FROM tenant_users u
                WHERE u.tenant_id = t.id
                  AND lower(u.email) = CAST(:email AS text)
            )
            """
        ),
        {"email": SYSTEM_UNASSIGN_EMAIL},
    )


def downgrade() -> None:
    op.get_bind().execute(
        sa.text("DELETE FROM tenant_users WHERE lower(email) = CAST(:email AS text)"),
        {"email": SYSTEM_UNASSIGN_EMAIL},
    )
