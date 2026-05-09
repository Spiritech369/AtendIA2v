"""028_session3_loophole_closures

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-05-08

Closes loopholes the previous sessions documented as TODOs:

- ``workflows.version`` (INTEGER NOT NULL DEFAULT 1) — optimistic-locking
  column. PATCH/toggle compare-and-swap against this so two concurrent
  admin edits stop stomping each other.
- ``events.conversation_id`` becomes nullable. Admin actions
  (workflow create/patch/delete/toggle, KB document upload/delete/retry/
  download) now emit audit events that don't have a conversation context.
  The audit-log read route already tolerates NULL ``conversation_id`` —
  this DDL just lets us write them.
- ``events.actor_user_id`` (UUID NULL) — who took the action. NULL when
  the writer is the system itself (workflow engine, NLU, etc).
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e5f6a7b8c9d0"
down_revision: str | Sequence[str] | None = "d4e5f6a7b8c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "workflows",
        sa.Column(
            "version",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )

    op.alter_column(
        "events",
        "conversation_id",
        nullable=True,
        existing_type=sa.UUID(),
    )

    op.add_column(
        "events",
        sa.Column(
            "actor_user_id",
            sa.UUID(),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_events_actor_user_id",
        "events",
        "tenant_users",
        ["actor_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "idx_events_actor_user_id",
        "events",
        ["actor_user_id"],
        postgresql_where=sa.text("actor_user_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_events_actor_user_id", table_name="events")
    op.drop_constraint("fk_events_actor_user_id", "events", type_="foreignkey")
    op.drop_column("events", "actor_user_id")

    op.alter_column(
        "events",
        "conversation_id",
        nullable=False,
        existing_type=sa.UUID(),
    )

    op.drop_column("workflows", "version")
