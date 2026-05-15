"""010_turn_traces_index

Revision ID: 9a35558e5d5f
Revises: a5b722986579
Create Date: 2026-05-03 21:08:07.860282

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9a35558e5d5f"
down_revision: Union[str, Sequence[str], None] = "a5b722986579"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_turn_traces_tenant_created",
        "turn_traces",
        ["tenant_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_turn_traces_tenant_created", table_name="turn_traces")
