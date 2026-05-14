"""047_tenant_advisors_vehicles

Revision ID: m0a1b2c3d4e5
Revises: l9a0b1c2d3e4
Create Date: 2026-05-14

Adds tenant-scoped `advisors` and `vehicles` tables so non-demo tenants
can populate their own asesores/unidades instead of seeing an empty
dropdown in /appointments. Before this migration, the only data sources
were the hardcoded `DEMO_ADVISORS` / `DEMO_VEHICLES` constants — gated
behind `tenant.is_demo` — leaving every real tenant with EmptyAdvisor /
EmptyVehicle providers (Sprint A.2 fix).

Schema deliberately tracks the dict shape returned by the demo
providers so DB-backed and demo providers are wire-compatible:
- advisors: id (slug), tenant_id, name, phone, max_per_day, close_rate
- vehicles: id (slug), tenant_id, label, status, available_for_test_drive

Composite primary key `(tenant_id, id)` lets two tenants each own a
slug like `maria_gonzalez` without collision while staying compatible
with `appointments.advisor_id String(80)` — the appointment row already
knows its tenant via its own `tenant_id`, so the implicit join is
unambiguous.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "m0a1b2c3d4e5"
down_revision: str | Sequence[str] | None = "l9a0b1c2d3e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "advisors",
        sa.Column("tenant_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("id", sa.String(80), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("phone", sa.String(40), nullable=True),
        sa.Column("max_per_day", sa.Integer(), nullable=False, server_default=sa.text("6")),
        sa.Column("close_rate", sa.Float(), nullable=False, server_default=sa.text("0.0")),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("tenant_id", "id", name="pk_advisors"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_advisors_tenant_id", "advisors", ["tenant_id"])

    op.create_table(
        "vehicles",
        sa.Column("tenant_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("id", sa.String(80), nullable=False),
        sa.Column("label", sa.String(160), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="available"),
        sa.Column(
            "available_for_test_drive",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("tenant_id", "id", name="pk_vehicles"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_vehicles_tenant_id", "vehicles", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("ix_vehicles_tenant_id", table_name="vehicles")
    op.drop_table("vehicles")
    op.drop_index("ix_advisors_tenant_id", table_name="advisors")
    op.drop_table("advisors")
