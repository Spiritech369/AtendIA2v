"""043_field_suggestions

Revision ID: i6d7e8f9a0b1
Revises: h5c6d7e8f9a0
Create Date: 2026-05-13
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "i6d7e8f9a0b1"
down_revision: str | Sequence[str] | None = "h5c6d7e8f9a0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "field_suggestions",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("customer_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "conversation_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("turn_number", sa.Integer(), nullable=True),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("suggested_value", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=False),
        sa.Column("evidence_text", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "decided_by_user_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["decided_by_user_id"], ["tenant_users.id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "status IN ('pending','accepted','rejected')",
            name="ck_field_suggestions_status",
        ),
    )
    op.create_index(
        "ix_field_suggestions_tenant_customer_status",
        "field_suggestions",
        ["tenant_id", "customer_id", "status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_field_suggestions_tenant_customer_status",
        table_name="field_suggestions",
    )
    op.drop_table("field_suggestions")
