"""051_workflow_executions_w6_w8

Revision ID: q3e4f5g6h7i8
Revises: p2d3e4f5g6h7
Create Date: 2026-05-15

W6+W8 — workflow_executions gains two nullable columns + a self-FK:

* parent_execution_id (UUID, FK → workflow_executions.id) — set when a
  trigger_workflow node creates a child execution. Walked at execute
  time to detect recursion.
* awaiting_variable (String(80)) — set by ask_question when it pauses
  the execution. The MESSAGE_RECEIVED handler reads this to know
  which variable to fill on resume.

Both nullable so legacy executions stay valid. ON DELETE SET NULL on
the parent FK so deleting an old parent execution doesn't cascade
through child history.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "q3e4f5g6h7i8"
down_revision: str | Sequence[str] | None = "p2d3e4f5g6h7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "workflow_executions",
        sa.Column(
            "parent_execution_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_workflow_executions_parent",
        "workflow_executions",
        "workflow_executions",
        ["parent_execution_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_workflow_executions_parent",
        "workflow_executions",
        ["parent_execution_id"],
    )
    op.add_column(
        "workflow_executions",
        sa.Column("awaiting_variable", sa.String(80), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("workflow_executions", "awaiting_variable")
    op.drop_index("ix_workflow_executions_parent", table_name="workflow_executions")
    op.drop_constraint(
        "fk_workflow_executions_parent",
        "workflow_executions",
        type_="foreignkey",
    )
    op.drop_column("workflow_executions", "parent_execution_id")
