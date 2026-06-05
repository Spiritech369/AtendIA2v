"""062_onboarding_state

Tenant-scoped Agent-First onboarding wizard state.
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0nb04rd1ngv1"
down_revision: str | Sequence[str] | None = "ac710nexecv2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "onboarding_states",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("selected_blueprint_id", sa.String(length=120), nullable=True),
        sa.Column("channel_connected", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("knowledge_uploaded", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("agent_configured", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("contact_fields_ready", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("lifecycle_ready", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("test_passed", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("published", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "current_step",
            sa.String(length=80),
            nullable=False,
            server_default="select_blueprint",
        ),
        sa.Column(
            "checklist",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
    )


def downgrade() -> None:
    op.drop_table("onboarding_states")
