from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.db.models import TenantCatalogItem
from atendia.tools.base import Tool


class QuoteInput(BaseModel):
    tenant_id: UUID
    sku: str
    options: dict = {}


class QuoteTool(Tool):
    name = "quote"

    async def run(self, session: AsyncSession, **kwargs: Any) -> dict:
        params = QuoteInput.model_validate(kwargs)
        stmt = select(TenantCatalogItem).where(
            TenantCatalogItem.tenant_id == params.tenant_id,
            TenantCatalogItem.sku == params.sku,
        )
        item = (await session.execute(stmt)).scalar_one_or_none()
        if item is None:
            return {"error": "sku_not_found", "sku": params.sku}
        # Stub pricing logic — real lives in Fase 3
        base_price = Decimal(str(item.attrs.get("price_mxn", "0")))
        return {
            "sku": item.sku,
            "name": item.name,
            "price_mxn": str(base_price),
            "options_applied": params.options,
        }
