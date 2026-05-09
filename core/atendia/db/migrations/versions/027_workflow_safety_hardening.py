"""027_workflow_safety_hardening

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-05-08

Adds the columns the workflow engine needs to be safe:

- ``events.source_workflow_execution_id`` — nullable FK to
  ``workflow_executions``. Engine tags every event it produces; ``evaluate_event``
  uses it to short-circuit self-triggering workflows.
- ``workflow_executions.steps_completed`` — counter persisted across
  delay/resume so the ``MAX_STEPS`` cap can't be sidestepped by chaining
  ``message → delay 1s`` indefinitely.
- ``workflow_executions.error_code`` — structured failure code
  (e.g. ``OUTSIDE_24H_WINDOW``) alongside the freeform ``error`` string.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d4e5f6a7b8c9"
down_revision: str | Sequence[str] | None = "c3d4e5f6a7b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "events",
        sa.Column("source_workflow_execution_id", sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        "fk_events_source_workflow_execution_id",
        "events",
        "workflow_executions",
        ["source_workflow_execution_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "idx_events_source_workflow_execution_id",
        "events",
        ["source_workflow_execution_id"],
        postgresql_where=sa.text("source_workflow_execution_id IS NOT NULL"),
    )

    op.add_column(
        "workflow_executions",
        sa.Column(
            "steps_completed",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "workflow_executions",
        sa.Column("error_code", sa.String(60), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("workflow_executions", "error_code")
    op.drop_column("workflow_executions", "steps_completed")
    op.drop_index(
        "idx_events_source_workflow_execution_id",
        table_name="events",
    )
    op.drop_constraint(
        "fk_events_source_workflow_execution_id",
        "events",
        type_="foreignkey",
    )
    op.drop_column("events", "source_workflow_execution_id")
