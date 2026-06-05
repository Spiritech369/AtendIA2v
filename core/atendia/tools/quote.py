"""Tenant-neutral quote tool."""

from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.catalog_runtime import (
    catalog_cash_price_mxn,
    catalog_list_price_mxn,
    catalog_payment_options,
    catalog_product_details,
)
from atendia.commercial_catalog_service import (
    get_catalog_item_for_quote,
    has_published_catalogs,
)
from atendia.db.models import TenantCatalogItem
from atendia.tools.base import Quote, Tool, ToolNoDataResult


def _decimal_or_zero(value: Any) -> Decimal:
    """Parse a JSONB value as Decimal; fall back to 0 when missing/invalid."""
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
    plan_code: str | None = None,
) -> Quote | ToolNoDataResult:
    """Look up an active catalog SKU and return its neutral quote payload."""
    if await has_published_catalogs(session, tenant_id=tenant_id):
        runtime_result: dict[str, Any] = {}
        for candidate_plan in _plan_code_candidates(plan_code):
            runtime_result = await get_catalog_item_for_quote(
                session,
                tenant_id=tenant_id,
                sku=sku,
                plan_code=candidate_plan,
            )
            if runtime_result.get("status") != "missing_data":
                break
        if runtime_result.get("status") == "ok":
            item = runtime_result.get("item") or {}
            plan = runtime_result.get("plan") or {}
            payment_options = {}
            if plan:
                plan_code = str(plan.get("plan_code") or "default")
                eligibility = (
                    plan.get("eligibility_rules_json")
                    if isinstance(plan.get("eligibility_rules_json"), dict)
                    else {}
                )
                payment_options[plan_code] = {
                    "down_payment_mxn": plan.get("down_payment_amount"),
                    "enganche_mxn": plan.get("down_payment_amount"),
                    "installment_mxn": plan.get("installment_amount"),
                    "pago_quincenal_mxn": plan.get("installment_amount"),
                    "frequency": plan.get("installment_frequency"),
                    "term_count": plan.get("installment_count"),
                    "numero_quincenas": plan.get("installment_count"),
                    "term_months": plan.get("term_months"),
                    "plazo_texto": eligibility.get("plazo_texto"),
                }
            attributes = item.get("attributes") if isinstance(item.get("attributes"), dict) else {}
            return Quote(
                sku=str(item.get("sku") or sku),
                name=str(item.get("name") or sku),
                category=str(item.get("category") or attributes.get("category") or ""),
                list_price_mxn=_decimal_or_zero(item.get("list_price")),
                cash_price_mxn=_decimal_or_zero(item.get("base_price") or item.get("list_price")),
                payment_options=payment_options,
                product_details=attributes,
                source=(
                    runtime_result.get("source")
                    if isinstance(runtime_result.get("source"), dict)
                    else {}
                ),
            )
        missing = runtime_result.get("missing")
        if isinstance(missing, list) and missing:
            hint = f"missing data for quote: {', '.join(str(item) for item in missing)}"
        else:
            hint = runtime_result.get("hint") or f"sku {sku!r} not found in published catalog"
        return ToolNoDataResult(hint=str(hint))

    stmt = select(TenantCatalogItem).where(
        TenantCatalogItem.tenant_id == tenant_id,
        TenantCatalogItem.sku == sku,
        TenantCatalogItem.active.is_(True),
    )
    item = (await session.execute(stmt)).scalar_one_or_none()
    if item is None:
        return ToolNoDataResult(hint=f"sku {sku!r} not found in active catalog")

    payment_options = catalog_payment_options(item)
    selected_payment_options = _filter_payment_options(payment_options, plan_code)

    return Quote(
        sku=item.sku,
        name=item.name,
        category=item.category or (item.attrs or {}).get("category", ""),
        list_price_mxn=_decimal_or_zero(catalog_list_price_mxn(item)),
        cash_price_mxn=_decimal_or_zero(catalog_cash_price_mxn(item)),
        payment_options=selected_payment_options or payment_options,
        product_details=catalog_product_details(item),
    )


class QuoteTool(Tool):  # pragma: no cover
    """Registry wrapper; new runtime paths call ``quote`` directly."""

    name = "quote"

    async def run(self, session: AsyncSession, **kwargs: Any) -> dict:
        result = await quote(
            session=session,
            tenant_id=kwargs["tenant_id"],
            sku=kwargs["sku"],
            plan_code=kwargs.get("plan_code"),
        )
        return result.model_dump(mode="json")


def _plan_code_candidates(plan_code: str | None) -> list[str | None]:
    """Return equivalent plan identifiers without hardcoding a tenant vertical."""
    if plan_code is None:
        return [None]
    raw = str(plan_code).strip()
    if not raw:
        return [None]
    variants = [raw]
    if raw.endswith("%"):
        variants.append(raw.rstrip("%").strip())
    else:
        variants.append(f"{raw}%")
    seen: set[str] = set()
    out: list[str | None] = []
    for value in variants:
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out


def _filter_payment_options(
    payment_options: dict[str, Any],
    plan_code: str | None,
) -> dict[str, Any]:
    if not payment_options or plan_code is None:
        return {}
    normalized_candidates = {
        str(candidate).strip().casefold()
        for candidate in _plan_code_candidates(plan_code)
        if candidate is not None
    }
    if not normalized_candidates:
        return {}
    for key, value in payment_options.items():
        key_norm = str(key).strip().casefold()
        plan_norm = str(value.get("plan") if isinstance(value, dict) else "").strip().casefold()
        name_norm = str(value.get("name") if isinstance(value, dict) else "").strip().casefold()
        if (
            key_norm in normalized_candidates
            or plan_norm in normalized_candidates
            or name_norm in normalized_candidates
        ):
            return {key: value}
    return {}
