"""022_customer_field_definitions

Revision ID: e8f9a0b1c2d3
Revises: d7e8f9a0b1c2
Create Date: 2026-05-07 22:01:00.000000

Step 1 backend prep — tenant-scoped custom field definitions.
Each tenant can define their own customer fields (text, number, date,
select, multiselect, checkbox). field_options stores select/multiselect
choices as JSONB.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e8f9a0b1c2d3"
down_revision: str | Sequence[str] | None = "d7e8f9a0b1c2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "customer_field_definitions",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.UUID(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("key", sa.String(120), nullable=False),
        sa.Column("label", sa.String(200), nullable=False),
        sa.Column("field_type", sa.String(40), nullable=False),
        sa.Column("field_options", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column(
            "ordering", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("tenant_id", "key", name="uq_field_defs_tenant_key"),
    )


def downgrade() -> None:
    op.drop_table("customer_field_definitions")
