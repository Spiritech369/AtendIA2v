"""drop pipeline tone field

Revision ID: 4329f44c0243
Revises: 9a35558e5d5f
Create Date: 2026-05-05 15:13:50.603813

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "4329f44c0243"
down_revision: Union[str, Sequence[str], None] = "9a35558e5d5f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("UPDATE tenant_pipelines SET definition = definition - 'tone'")


def downgrade() -> None:
    op.execute(
        "UPDATE tenant_pipelines "
        "SET definition = definition || jsonb_build_object('tone', '{}'::jsonb) "
        "WHERE NOT (definition ? 'tone')"
    )
