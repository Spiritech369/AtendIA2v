"""069_respond_style_shadow_fields

Isolated, auditable shadow contact-field state for the Respond-Style
direct route (no-send/shadow only). Nothing in the legacy runner reads or
writes this table; live commercial state remains untouched.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "productagents069"
down_revision: str | Sequence[str] | None = "productagents068"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "respond_style_shadow_fields",
        sa.Column("conversation_id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column(
            "field_values",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "audit_log",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["conversations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("conversation_id"),
    )
    op.create_index(
        "ix_respond_style_shadow_fields_tenant_id",
        "respond_style_shadow_fields",
        ["tenant_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_respond_style_shadow_fields_tenant_id",
        table_name="respond_style_shadow_fields",
    )
    op.drop_table("respond_style_shadow_fields")
