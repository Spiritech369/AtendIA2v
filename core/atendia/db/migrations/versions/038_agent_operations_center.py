"""038_agent_operations_center

Revision ID: d1e2f3a4b5c6
Revises: c0d1e2f3a4b5
Create Date: 2026-05-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d1e2f3a4b5c6"
down_revision: str | Sequence[str] | None = "c0d1e2f3a4b5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agents",
        sa.Column("status", sa.String(20), nullable=False, server_default="production"),
    )
    op.add_column(
        "agents",
        sa.Column("behavior_mode", sa.String(20), nullable=False, server_default="normal"),
    )
    op.add_column(
        "agents",
        sa.Column("version", sa.String(20), nullable=False, server_default="v2.4"),
    )
    op.add_column("agents", sa.Column("dealership_id", sa.String(80), nullable=True))
    op.add_column("agents", sa.Column("branch_id", sa.String(80), nullable=True))
    op.add_column(
        "agents",
        sa.Column(
            "ops_config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.create_index("ix_agents_status", "agents", ["tenant_id", "status"])
    op.create_index("ix_agents_role", "agents", ["tenant_id", "role"])


def downgrade() -> None:
    op.drop_index("ix_agents_role", table_name="agents")
    op.drop_index("ix_agents_status", table_name="agents")
    op.drop_column("agents", "ops_config")
    op.drop_column("agents", "branch_id")
    op.drop_column("agents", "dealership_id")
    op.drop_column("agents", "version")
    op.drop_column("agents", "behavior_mode")
    op.drop_column("agents", "status")
