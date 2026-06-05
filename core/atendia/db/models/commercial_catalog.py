from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from atendia.db.base import Base


class Catalog(Base):
    __tablename__ = "catalogs"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        index=True,
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    vertical: Mapped[str] = mapped_column(String(40), nullable=False)
    currency: Mapped[str] = mapped_column(
        String(8),
        nullable=False,
        default="MXN",
        server_default="MXN",
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="draft",
        server_default="draft",
    )
    active_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("catalog_versions.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CatalogItem(Base):
    __tablename__ = "catalog_items"
    __table_args__ = (
        UniqueConstraint("catalog_id", "sku", name="uq_catalog_items_catalog_sku"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        index=True,
    )
    catalog_id: Mapped[UUID] = mapped_column(
        ForeignKey("catalogs.id", ondelete="CASCADE"),
        index=True,
    )
    sku: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    type: Mapped[str | None] = mapped_column(String(60))
    category: Mapped[str | None] = mapped_column(String(80), index=True)
    base_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    list_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    stock_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="unknown",
        server_default="unknown",
    )
    stock_quantity: Mapped[int | None] = mapped_column(Integer)
    branch_id: Mapped[str | None] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="draft",
        server_default="draft",
    )
    attributes_json: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    ai_rules_json: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    tags_json: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CatalogItemPlan(Base):
    __tablename__ = "catalog_item_plans"
    __table_args__ = (
        UniqueConstraint("catalog_item_id", "plan_code", name="uq_catalog_item_plans_item_plan_code"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        index=True,
    )
    catalog_item_id: Mapped[UUID] = mapped_column(
        ForeignKey("catalog_items.id", ondelete="CASCADE"),
        index=True,
    )
    plan_name: Mapped[str] = mapped_column(String(120), nullable=False)
    plan_code: Mapped[str] = mapped_column(String(80), nullable=False)
    plan_type: Mapped[str | None] = mapped_column(String(40))
    down_payment_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    down_payment_percent: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    installment_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    installment_frequency: Mapped[str | None] = mapped_column(String(20))
    installment_count: Mapped[int | None] = mapped_column(Integer)
    term_months: Mapped[int | None] = mapped_column(Integer)
    eligibility_rules_json: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="draft",
        server_default="draft",
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CatalogVersion(Base):
    __tablename__ = "catalog_versions"
    __table_args__ = (
        UniqueConstraint("catalog_id", "version_number", name="uq_catalog_versions_catalog_version"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        index=True,
    )
    catalog_id: Mapped[UUID] = mapped_column(
        ForeignKey("catalogs.id", ondelete="CASCADE"),
        index=True,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="draft",
        server_default="draft",
    )
    snapshot_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("tenant_users.id", ondelete="SET NULL"))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CatalogImportJob(Base):
    __tablename__ = "catalog_import_jobs"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        index=True,
    )
    catalog_id: Mapped[UUID] = mapped_column(
        ForeignKey("catalogs.id", ondelete="CASCADE"),
        index=True,
    )
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_type: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="uploaded",
        server_default="uploaded",
    )
    rows_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    rows_valid: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    rows_error: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    column_mapping_json: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    validation_errors_json: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    payload_json: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    storage_key: Mapped[str | None] = mapped_column(String(500))
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("tenant_users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CatalogExportJob(Base):
    __tablename__ = "catalog_export_jobs"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        index=True,
    )
    catalog_id: Mapped[UUID] = mapped_column(
        ForeignKey("catalogs.id", ondelete="CASCADE"),
        index=True,
    )
    file_type: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="processing",
        server_default="processing",
    )
    filters_json: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    download_url: Mapped[str | None] = mapped_column(String(500))
    storage_key: Mapped[str | None] = mapped_column(String(500))
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("tenant_users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
