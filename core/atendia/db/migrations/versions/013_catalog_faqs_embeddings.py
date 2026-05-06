"""catalog faqs embeddings

Revision ID: de4463588cea
Revises: c9c3bfbc5157
Create Date: 2026-05-06 02:18:19.763625

Phase 3c.1 — adds:

  * `tenant_catalogs.embedding   halfvec(3072)`  (text-embedding-3-large)
  * `tenant_catalogs.category    varchar(60)`     (e.g. "motoneta", "deportiva")
  * `tenant_faqs.embedding       halfvec(3072)`
  * HNSW indexes on both `embedding` columns with `halfvec_cosine_ops`
  * UNIQUE (tenant_id, question) on `tenant_faqs` for idempotent ingestion

Why halfvec instead of vector
-----------------------------

`text-embedding-3-large` returns 3072-dim float vectors. pgvector's HNSW index
is hard-capped at 2000 dimensions for the standard `vector` type — anything
larger errors out at index creation. `halfvec` (half-precision, 16-bit floats)
raises that cap to 4000 dimensions, which covers our 3072-dim use case while
also halving on-disk storage (~6 KB/row vs ~12 KB/row).

Recall trade-off: empirical evaluation on text-embedding-3-large shows <0.5%
recall loss at top-k for halfvec vs full-precision (the dominant signal lives
in the highest-magnitude components, which round-trip cleanly). For our
catalog of ~30 motorcycles + ~12 FAQs this is well below noise.

Cosine ops: `halfvec_cosine_ops` is the halfvec analogue of `vector_cosine_ops`;
the `<=>` distance operator works identically against query vectors of either
type with an explicit cast.

HNSW params m=16 / ef_construction=64 are pgvector defaults — well-suited to
small corpora and cheap to rebuild if we tune later.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import HALFVEC


# revision identifiers, used by Alembic.
revision: str = 'de4463588cea'
down_revision: Union[str, Sequence[str], None] = 'c9c3bfbc5157'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_HNSW_PARAMS: dict[str, int] = {"m": 16, "ef_construction": 64}


def upgrade() -> None:
    """Add embedding + category columns and HNSW indexes."""

    # tenant_catalogs ----------------------------------------------------
    op.add_column(
        "tenant_catalogs",
        sa.Column("embedding", HALFVEC(3072), nullable=True),
    )
    op.add_column(
        "tenant_catalogs",
        sa.Column("category", sa.String(60), nullable=True),
    )
    op.create_index(
        "ix_tenant_catalogs_category",
        "tenant_catalogs",
        ["tenant_id", "category"],
    )
    op.create_index(
        "ix_tenant_catalogs_embedding",
        "tenant_catalogs",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_with=_HNSW_PARAMS,
        postgresql_ops={"embedding": "halfvec_cosine_ops"},
    )

    # tenant_faqs --------------------------------------------------------
    op.add_column(
        "tenant_faqs",
        sa.Column("embedding", HALFVEC(3072), nullable=True),
    )
    op.create_index(
        "ix_tenant_faqs_embedding",
        "tenant_faqs",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_with=_HNSW_PARAMS,
        postgresql_ops={"embedding": "halfvec_cosine_ops"},
    )
    op.create_unique_constraint(
        "uq_tenant_faqs_tenant_question",
        "tenant_faqs",
        ["tenant_id", "question"],
    )


def downgrade() -> None:
    """Reverse upgrade in dependency order (constraint, indexes, columns)."""
    op.drop_constraint("uq_tenant_faqs_tenant_question", "tenant_faqs", type_="unique")
    op.drop_index("ix_tenant_faqs_embedding", table_name="tenant_faqs")
    op.drop_column("tenant_faqs", "embedding")
    op.drop_index("ix_tenant_catalogs_embedding", table_name="tenant_catalogs")
    op.drop_index("ix_tenant_catalogs_category", table_name="tenant_catalogs")
    op.drop_column("tenant_catalogs", "category")
    op.drop_column("tenant_catalogs", "embedding")
