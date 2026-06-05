"""057_commercial_catalog_module

Global commercial catalog module:
- multi-tenant catalogs
- catalog items + plans
- versioned snapshots for runtime-safe quoting
- import/export jobs
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "w9k0l1m2n3o4"
down_revision: str | Sequence[str] | None = "v8j9k0l1m2n3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "catalogs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("vertical", sa.String(length=40), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False, server_default="MXN"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"),
        sa.Column("active_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "status IN ('active', 'inactive', 'draft', 'archived')",
            name="ck_catalogs_status",
        ),
    )
    op.create_index("ix_catalogs_tenant_id", "catalogs", ["tenant_id"], unique=False)
    op.create_index("ix_catalogs_vertical", "catalogs", ["vertical"], unique=False)

    op.create_table(
        "catalog_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("catalog_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"),
        sa.Column(
            "snapshot_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["catalog_id"], ["catalogs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["tenant_users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("catalog_id", "version_number", name="uq_catalog_versions_catalog_version"),
        sa.CheckConstraint(
            "status IN ('draft', 'published', 'archived')",
            name="ck_catalog_versions_status",
        ),
    )
    op.create_index("ix_catalog_versions_tenant_id", "catalog_versions", ["tenant_id"], unique=False)
    op.create_index("ix_catalog_versions_catalog_id", "catalog_versions", ["catalog_id"], unique=False)
    op.create_foreign_key(
        "fk_catalogs_active_version_id",
        "catalogs",
        "catalog_versions",
        ["active_version_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "catalog_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("catalog_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sku", sa.String(length=120), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("type", sa.String(length=60), nullable=True),
        sa.Column("category", sa.String(length=80), nullable=True),
        sa.Column("base_price", sa.Numeric(14, 2), nullable=True),
        sa.Column("list_price", sa.Numeric(14, 2), nullable=True),
        sa.Column("stock_status", sa.String(length=20), nullable=False, server_default="unknown"),
        sa.Column("stock_quantity", sa.Integer(), nullable=True),
        sa.Column("branch_id", sa.String(length=80), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"),
        sa.Column(
            "attributes_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "ai_rules_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "tags_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["catalog_id"], ["catalogs.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("catalog_id", "sku", name="uq_catalog_items_catalog_sku"),
        sa.CheckConstraint(
            "status IN ('active', 'inactive', 'draft', 'archived')",
            name="ck_catalog_items_status",
        ),
        sa.CheckConstraint(
            "stock_status IN ('available', 'unavailable', 'unknown', 'limited')",
            name="ck_catalog_items_stock_status",
        ),
    )
    op.create_index("ix_catalog_items_tenant_id", "catalog_items", ["tenant_id"], unique=False)
    op.create_index("ix_catalog_items_catalog_id", "catalog_items", ["catalog_id"], unique=False)
    op.create_index("ix_catalog_items_category", "catalog_items", ["category"], unique=False)

    op.create_table(
        "catalog_item_plans",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("catalog_item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("plan_name", sa.String(length=120), nullable=False),
        sa.Column("plan_code", sa.String(length=80), nullable=False),
        sa.Column("plan_type", sa.String(length=40), nullable=True),
        sa.Column("down_payment_amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("down_payment_percent", sa.Numeric(8, 4), nullable=True),
        sa.Column("installment_amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("installment_frequency", sa.String(length=20), nullable=True),
        sa.Column("installment_count", sa.Integer(), nullable=True),
        sa.Column("term_months", sa.Integer(), nullable=True),
        sa.Column(
            "eligibility_rules_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["catalog_item_id"], ["catalog_items.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("catalog_item_id", "plan_code", name="uq_catalog_item_plans_item_plan_code"),
        sa.CheckConstraint(
            "status IN ('active', 'inactive', 'draft', 'archived')",
            name="ck_catalog_item_plans_status",
        ),
    )
    op.create_index(
        "ix_catalog_item_plans_tenant_id",
        "catalog_item_plans",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        "ix_catalog_item_plans_catalog_item_id",
        "catalog_item_plans",
        ["catalog_item_id"],
        unique=False,
    )

    op.create_table(
        "catalog_import_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("catalog_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("file_type", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="uploaded"),
        sa.Column("rows_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rows_valid", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rows_error", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "column_mapping_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "validation_errors_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "payload_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("storage_key", sa.String(length=500), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["catalog_id"], ["catalogs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["tenant_users.id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "status IN ('uploaded', 'previewed', 'validated', 'invalid', 'draft_saved', 'published', 'failed')",
            name="ck_catalog_import_jobs_status",
        ),
    )
    op.create_index(
        "ix_catalog_import_jobs_tenant_id",
        "catalog_import_jobs",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        "ix_catalog_import_jobs_catalog_id",
        "catalog_import_jobs",
        ["catalog_id"],
        unique=False,
    )

    op.create_table(
        "catalog_export_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("catalog_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("file_type", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="processing"),
        sa.Column(
            "filters_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("download_url", sa.String(length=500), nullable=True),
        sa.Column("storage_key", sa.String(length=500), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["catalog_id"], ["catalogs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["tenant_users.id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "status IN ('processing', 'ready', 'failed')",
            name="ck_catalog_export_jobs_status",
        ),
    )
    op.create_index(
        "ix_catalog_export_jobs_tenant_id",
        "catalog_export_jobs",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        "ix_catalog_export_jobs_catalog_id",
        "catalog_export_jobs",
        ["catalog_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_catalog_export_jobs_catalog_id", table_name="catalog_export_jobs")
    op.drop_index("ix_catalog_export_jobs_tenant_id", table_name="catalog_export_jobs")
    op.drop_table("catalog_export_jobs")

    op.drop_index("ix_catalog_import_jobs_catalog_id", table_name="catalog_import_jobs")
    op.drop_index("ix_catalog_import_jobs_tenant_id", table_name="catalog_import_jobs")
    op.drop_table("catalog_import_jobs")

    op.drop_index("ix_catalog_item_plans_catalog_item_id", table_name="catalog_item_plans")
    op.drop_index("ix_catalog_item_plans_tenant_id", table_name="catalog_item_plans")
    op.drop_table("catalog_item_plans")

    op.drop_index("ix_catalog_items_category", table_name="catalog_items")
    op.drop_index("ix_catalog_items_catalog_id", table_name="catalog_items")
    op.drop_index("ix_catalog_items_tenant_id", table_name="catalog_items")
    op.drop_table("catalog_items")

    op.drop_constraint("fk_catalogs_active_version_id", "catalogs", type_="foreignkey")
    op.drop_index("ix_catalog_versions_catalog_id", table_name="catalog_versions")
    op.drop_index("ix_catalog_versions_tenant_id", table_name="catalog_versions")
    op.drop_table("catalog_versions")

    op.drop_index("ix_catalogs_vertical", table_name="catalogs")
    op.drop_index("ix_catalogs_tenant_id", table_name="catalogs")
    op.drop_table("catalogs")
