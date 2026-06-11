"""070_smoke_takeover_pending

Phase 20: human-takeover marker on the isolated Respond-Style shadow table.
Set when an accepted handoff ack is staged during single-contact smoke; the
direct route stops auto-responding for that conversation until a human takes
over or rollback/reset clears it.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "productagents070"
down_revision: str | Sequence[str] | None = "productagents069"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "respond_style_shadow_fields",
        sa.Column(
            "takeover_pending",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("respond_style_shadow_fields", "takeover_pending")
