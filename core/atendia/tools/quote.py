"""Phase 3c.1 — real-data quote tool.

`quote(session, tenant_id, sku) -> Quote | ToolNoDataResult` is the
function-style interface the runner (T18) calls directly. The legacy
`QuoteTool(Tool)` class is preserved as a thin registry-compat wrapper
that delegates to the same function — `register_all_tools()` keeps
working unchanged, but new code paths import the function.

Money fields live in `attrs` JSONB (populated by ingestion in T13/T15)
because the catalog schema doesn't have dedicated price columns. We
parse them with `Decimal(str(...))` so floats and ints both round-trip
without precision loss.
"""
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.db.models import TenantCatalogItem
from atendia.tools.base import Quote, Tool, ToolNoDataResult


def _decimal_or_zero(value: Any) -> Decimal:
    """Parse a JSONB value as Decimal; fall back to 0 when missing/invalid.

    Treats `None`, `""`, and unparseable strings as 0. This mirrors the
    contract that `quote()` should still return a Quote (not crash) even
    if ingestion has only partial data — Composer can render `$0` and the
    operator can fix the catalog row.
    """
    if value is None or value == "":
        return Decimal("0")
    try:
        return Decimal(str(value))
    except (ValueError, ArithmeticError):
        return Decimal("0")


async def quote(
    *,
    session: AsyncSession,
    tenant_id: UUID,
    sku: str,
) -> Quote | ToolNoDataResult:
    """Look up an active catalog SKU and return its Quote.

    Returns `ToolNoDataResult` when:
      * the SKU is not in `tenant_catalogs`, or
      * the row exists but `active = false`.

    The hint mentions the requested SKU verbatim so the Composer prompt
    can echo it back ("no tengo info de la lambretta-200; ¿quieres
    que te muestre los modelos disponibles?").
    """
    stmt = select(TenantCatalogItem).where(
        TenantCatalogItem.tenant_id == tenant_id,
        TenantCatalogItem.sku == sku,
        TenantCatalogItem.active.is_(True),
    )
    item = (await session.execute(stmt)).scalar_one_or_none()
    if item is None:
        return ToolNoDataResult(hint=f"sku {sku!r} not found in active catalog")

    attrs: dict = item.attrs or {}
    return Quote(
        sku=item.sku,
        name=item.name,
        category=item.category or attrs.get("category", ""),
        price_lista_mxn=_decimal_or_zero(attrs.get("precio_lista")),
        price_contado_mxn=_decimal_or_zero(attrs.get("precio_contado")),
        planes_credito=attrs.get("planes_credito") or {},
        ficha_tecnica=attrs.get("ficha_tecnica") or {},
    )


class QuoteTool(Tool):
    """Legacy registry wrapper — delegates to `quote()` and dumps to dict.

    Phase 3c.1's runner (T18) calls `quote()` directly, but
    `register_all_tools()` still references the class so the registry's
    introspection tests stay green. Once nothing in the runner path uses
    the registry for `quote`, this wrapper can be removed (post-Phase 3c.1).
    """

    name = "quote"

    async def run(self, session: AsyncSession, **kwargs: Any) -> dict:
        result = await quote(
            session=session,
            tenant_id=kwargs["tenant_id"],
            sku=kwargs["sku"],
        )
        return result.model_dump(mode="json")
