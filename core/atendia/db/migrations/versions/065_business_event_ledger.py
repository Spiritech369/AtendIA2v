"""065_business_event_ledger

Persist universal business event idempotency before workflow execution.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "businesseventledger065"
down_revision: str | Sequence[str] | None = "agentvoice064"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "business_event_ledger",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("conversation_id", sa.UUID(), nullable=True),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("idempotency_key", sa.String(length=512), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "event_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "workflow_result",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("trace_id", sa.String(length=120), nullable=True),
        sa.Column(
            "side_effects_allowed",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "conversation_id",
            "event_type",
            "idempotency_key",
            name="uq_business_event_ledger_scope_idempotency_key",
        ),
    )
    op.create_index(
        op.f("ix_business_event_ledger_conversation_id"),
        "business_event_ledger",
        ["conversation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_business_event_ledger_event_type"),
        "business_event_ledger",
        ["event_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_business_event_ledger_idempotency_key"),
        "business_event_ledger",
        ["idempotency_key"],
        unique=False,
    )
    op.create_index(
        op.f("ix_business_event_ledger_tenant_id"),
        "business_event_ledger",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_business_event_ledger_trace_id"),
        "business_event_ledger",
        ["trace_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_business_event_ledger_trace_id"), table_name="business_event_ledger")
    op.drop_index(op.f("ix_business_event_ledger_tenant_id"), table_name="business_event_ledger")
    op.drop_index(
        op.f("ix_business_event_ledger_idempotency_key"),
        table_name="business_event_ledger",
    )
    op.drop_index(op.f("ix_business_event_ledger_event_type"), table_name="business_event_ledger")
    op.drop_index(
        op.f("ix_business_event_ledger_conversation_id"),
        table_name="business_event_ledger",
    )
    op.drop_table("business_event_ledger")
