from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from atendia.db.base import Base


class Advisor(Base):
    __tablename__ = "advisors"

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(40))
    max_per_day: Mapped[int] = mapped_column(Integer, nullable=False, server_default="6")
    close_rate: Mapped[float] = mapped_column(Float, nullable=False, server_default="0.0")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Vehicle(Base):
    __tablename__ = "vehicles"

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    label: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, server_default="available")
    available_for_test_drive: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
