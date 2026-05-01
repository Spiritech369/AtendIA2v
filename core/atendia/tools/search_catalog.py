from typing import Any
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.db.models import TenantCatalogItem
from atendia.tools.base import Tool


class SearchCatalogInput(BaseModel):
    tenant_id: UUID
    query: str
    limit: int = 5


class CatalogResult(BaseModel):
    sku: str
    name: str
    attrs: dict


class SearchCatalogTool(Tool):
    name = "search_catalog"

    async def run(self, session: AsyncSession, **kwargs: Any) -> dict:
        params = SearchCatalogInput.model_validate(kwargs)
        stmt = (
            select(TenantCatalogItem)
            .where(
                TenantCatalogItem.tenant_id == params.tenant_id,
                TenantCatalogItem.active.is_(True),
            )
            .where(TenantCatalogItem.name.ilike(f"%{params.query}%"))
            .limit(params.limit)
        )
        rows = (await session.execute(stmt)).scalars().all()
        return {
            "results": [
                CatalogResult(sku=r.sku, name=r.name, attrs=r.attrs).model_dump()
                for r in rows
            ]
        }
