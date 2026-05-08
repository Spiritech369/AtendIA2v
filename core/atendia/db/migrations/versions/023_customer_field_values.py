"""023_customer_field_values

Revision ID: f9a0b1c2d3e4
Revises: e8f9a0b1c2d3
Create Date: 2026-05-07 22:02:00.000000

Step 1 backend prep — per-customer values for custom field definitions.
Composite PK (customer_id, field_definition_id) — one value per
customer per field. Value stored as text; frontend interprets based
on the definition's field_type.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f9a0b1c2d3e4"
down_revision: str | Sequence[str] | None = "e8f9a0b1c2d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "customer_field_values",
        sa.Column(
            "customer_id",
            sa.UUID(),
            sa.ForeignKey("customers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "field_definition_id",
            sa.UUID(),
            sa.ForeignKey("customer_field_definitions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("customer_id", "field_definition_id"),
    )


def downgrade() -> None:
    op.drop_table("customer_field_values")
