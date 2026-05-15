"""029_session5_conversations_loopholes

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-05-09

Closes residual Conversations Enhanced loopholes from session 4's runbook:

- ``customers.email`` (VARCHAR(160), nullable) — v1 had email in the
  basic-info form; v2 dropped it. Adding it as nullable so existing rows
  don't need a backfill.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f6a7b8c9d0e1"
down_revision: str | Sequence[str] | None = "e5f6a7b8c9d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "customers",
        sa.Column("email", sa.String(160), nullable=True),
    )
    op.create_index(
        "idx_customers_tenant_email",
        "customers",
        ["tenant_id", "email"],
        postgresql_where=sa.text("email IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_customers_tenant_email", table_name="customers")
    op.drop_column("customers", "email")
