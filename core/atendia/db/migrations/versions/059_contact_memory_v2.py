"""059_contact_memory_v2

Contact Memory v2 evidence log for AI-proposed field updates.
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c0n7ac7memv2"
down_revision: str | Sequence[str] | None = "x0y1z2a3b4c5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "customer_field_update_evidence",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("field_definition_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("field_key", sa.String(length=120), nullable=False),
        sa.Column("old_value", sa.Text(), nullable=True),
        sa.Column("new_value", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("evidence_message_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("evidence_attachment_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("trace_id", sa.String(length=120), nullable=True),
        sa.Column("created_by", sa.String(length=120), nullable=True),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["field_definition_id"],
            ["customer_field_definitions.id"],
            ondelete="SET NULL",
        ),
    )
    op.create_index(
        "ix_customer_field_update_evidence_tenant_id",
        "customer_field_update_evidence",
        ["tenant_id"],
    )
    op.create_index(
        "ix_customer_field_update_evidence_customer_id",
        "customer_field_update_evidence",
        ["customer_id"],
    )
    op.create_index(
        "ix_customer_field_update_evidence_field_definition_id",
        "customer_field_update_evidence",
        ["field_definition_id"],
    )
    op.create_index(
        "ix_customer_field_update_evidence_field_key",
        "customer_field_update_evidence",
        ["field_key"],
    )
    op.create_index(
        "ix_customer_field_update_evidence_status",
        "customer_field_update_evidence",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_customer_field_update_evidence_status",
        table_name="customer_field_update_evidence",
    )
    op.drop_index(
        "ix_customer_field_update_evidence_field_key",
        table_name="customer_field_update_evidence",
    )
    op.drop_index(
        "ix_customer_field_update_evidence_field_definition_id",
        table_name="customer_field_update_evidence",
    )
    op.drop_index(
        "ix_customer_field_update_evidence_customer_id",
        table_name="customer_field_update_evidence",
    )
    op.drop_index(
        "ix_customer_field_update_evidence_tenant_id",
        table_name="customer_field_update_evidence",
    )
    op.drop_table("customer_field_update_evidence")
