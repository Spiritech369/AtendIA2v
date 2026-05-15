"""039_appointment_command_center

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-05-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e2f3a4b5c6d7"
down_revision: str | Sequence[str] | None = "d1e2f3a4b5c6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_appointments_status", "appointments", type_="check")
    op.drop_constraint("ck_appointments_created_by_type", "appointments", type_="check")

    op.add_column("appointments", sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "appointments",
        sa.Column("appointment_type", sa.String(30), nullable=False, server_default="follow_up"),
    )
    op.add_column(
        "appointments",
        sa.Column("timezone", sa.String(80), nullable=False, server_default="America/Mexico_City"),
    )
    op.add_column(
        "appointments",
        sa.Column("source", sa.String(40), nullable=False, server_default="manual"),
    )
    op.add_column("appointments", sa.Column("advisor_id", sa.String(80), nullable=True))
    op.add_column("appointments", sa.Column("advisor_name", sa.String(160), nullable=True))
    op.add_column("appointments", sa.Column("vehicle_id", sa.String(80), nullable=True))
    op.add_column("appointments", sa.Column("vehicle_label", sa.String(160), nullable=True))
    op.add_column("appointments", sa.Column("ai_confidence", sa.Float(), nullable=True))
    op.add_column(
        "appointments",
        sa.Column("risk_score", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "appointments",
        sa.Column("risk_level", sa.String(20), nullable=False, server_default="low"),
    )
    op.add_column(
        "appointments",
        sa.Column(
            "risk_reasons",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "appointments",
        sa.Column(
            "recommended_actions",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column("appointments", sa.Column("credit_plan", sa.String(120), nullable=True))
    op.add_column("appointments", sa.Column("down_payment_amount", sa.Integer(), nullable=True))
    op.add_column(
        "appointments",
        sa.Column("down_payment_confirmed", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "appointments",
        sa.Column("documents_complete", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "appointments",
        sa.Column("last_customer_reply_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "appointments", sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "appointments", sa.Column("arrived_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "appointments", sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "appointments", sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "appointments", sa.Column("no_show_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "appointments",
        sa.Column("reminder_status", sa.String(30), nullable=False, server_default="pending"),
    )
    op.add_column(
        "appointments",
        sa.Column("reminder_last_sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "appointments",
        sa.Column(
            "action_log",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "appointments",
        sa.Column(
            "ops_config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )

    op.create_check_constraint(
        "ck_appointments_status",
        "appointments",
        "status IN ('scheduled', 'confirmed', 'arrived', 'completed', 'cancelled', 'no_show', 'rescheduled')",
    )
    op.create_check_constraint(
        "ck_appointments_created_by_type",
        "appointments",
        "created_by_type IN ('user', 'bot', 'ai')",
    )
    op.create_index("ix_appointments_tenant_status", "appointments", ["tenant_id", "status"])
    op.create_index("ix_appointments_tenant_advisor", "appointments", ["tenant_id", "advisor_id"])
    op.create_index("ix_appointments_tenant_vehicle", "appointments", ["tenant_id", "vehicle_id"])


def downgrade() -> None:
    op.drop_index("ix_appointments_tenant_vehicle", table_name="appointments")
    op.drop_index("ix_appointments_tenant_advisor", table_name="appointments")
    op.drop_index("ix_appointments_tenant_status", table_name="appointments")
    op.drop_constraint("ck_appointments_created_by_type", "appointments", type_="check")
    op.drop_constraint("ck_appointments_status", "appointments", type_="check")
    # Downgrade is lossy: the previous schema only knew four appointment
    # statuses and two creator types. Normalize rows before reinstating the
    # legacy check constraints so round-trip downgrades work with real data.
    op.execute(
        """
        UPDATE appointments
        SET status = CASE
            WHEN status IN ('confirmed', 'arrived', 'rescheduled') THEN 'scheduled'
            ELSE status
        END
        WHERE status IN ('confirmed', 'arrived', 'rescheduled')
        """
    )
    op.execute(
        """
        UPDATE appointments
        SET created_by_type = 'bot'
        WHERE created_by_type = 'ai'
        """
    )
    op.create_check_constraint(
        "ck_appointments_status",
        "appointments",
        "status IN ('scheduled', 'completed', 'cancelled', 'no_show')",
    )
    op.create_check_constraint(
        "ck_appointments_created_by_type",
        "appointments",
        "created_by_type IN ('user', 'bot')",
    )
    for column in [
        "ops_config",
        "action_log",
        "reminder_last_sent_at",
        "reminder_status",
        "no_show_at",
        "cancelled_at",
        "completed_at",
        "arrived_at",
        "confirmed_at",
        "last_customer_reply_at",
        "documents_complete",
        "down_payment_confirmed",
        "down_payment_amount",
        "credit_plan",
        "recommended_actions",
        "risk_reasons",
        "risk_level",
        "risk_score",
        "ai_confidence",
        "vehicle_label",
        "vehicle_id",
        "advisor_name",
        "advisor_id",
        "source",
        "timezone",
        "appointment_type",
        "ends_at",
    ]:
        op.drop_column("appointments", column)
