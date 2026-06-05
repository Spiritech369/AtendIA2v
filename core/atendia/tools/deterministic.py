"""Public deterministic-tool facade for Knowledge Pack runtime decisions."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from decimal import Decimal, InvalidOperation
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.credit_plan_invariants import (
    build_credit_plan_menu,
    resolve_credit_plan_option,
)
from atendia.catalog_runtime import catalog_cash_price_mxn, catalog_list_price_mxn
from atendia.commercial_catalog_service import (
    has_published_catalogs,
)
from atendia.commercial_catalog_service import (
    search_catalog as search_published_catalog,
)
from atendia.contracts.pipeline_definition import PipelineDefinition
from atendia.db.models import TenantCatalogItem
from atendia.text_normalization import normalize_whatsapp_text
from atendia.tools.base import ToolNoDataResult
from atendia.tools.lookup_requirements import RequiredDoc, lookup_requirements


class CatalogListItem(BaseModel):
    sku: str
    name: str
    category: str = ""
    cash_price_mxn: Decimal = Decimal("0")
    list_price_mxn: Decimal | None = None
    score: float | None = None
    catalog_item_id: UUID | None = None
    collection_id: UUID | None = None
    source: dict[str, Any] = Field(default_factory=dict)


class CatalogListResult(BaseModel):
    status: Literal["ok"] = "ok"
    type: Literal["catalog_list"] = "catalog_list"
    category: str | None = None
    query: str = ""
    total_results: int = 0
    models: list[CatalogListItem] = Field(default_factory=list)
    source: dict[str, Any] = Field(default_factory=dict)


class CreditPlanResolutionResult(BaseModel):
    status: Literal["ok"] = "ok"
    type: Literal["credit_plan_resolution"] = "credit_plan_resolution"
    input: str
    field_name: str
    selection_key: str
    selection_label: str | None = None
    display_number: int | None = None
    visible_label: str | None = None
    down_payment: str | None = None
    requirements_key: str | None = None
    matched_alias: str
    confidence: float
    field_updates: dict[str, str]
    source: dict[str, Any] = Field(default_factory=dict)


class MissingDocumentsResult(BaseModel):
    status: Literal["ok"] = "ok"
    type: Literal["missing_documents"] = "missing_documents"
    selection_field: str
    selection_key: str
    selection_label: str | None = None
    required: list[RequiredDoc] = Field(default_factory=list)
    received: list[RequiredDoc] = Field(default_factory=list)
    rejected: list[RequiredDoc] = Field(default_factory=list)
    missing: list[RequiredDoc] = Field(default_factory=list)
    complete: bool = False
    source: dict[str, Any] = Field(default_factory=dict)


async def list_catalog(
    *,
    session: AsyncSession,
    tenant_id: UUID,
    category: str | None = None,
    query: str = "",
    limit: int = 50,
    collection_ids: list[UUID] | None = None,
) -> CatalogListResult | ToolNoDataResult:
    """List tenant catalog items from the published catalog runtime.

    Falls back to legacy ``tenant_catalogs`` rows only when the tenant has no
    published commercial catalog yet. The public surface is intentionally the
    structured ``catalog_list`` payload consumed by the runner/composer traces.
    """

    cleaned_query = (query or "").strip()
    cleaned_category = (category or "").strip() or None
    safe_limit = max(1, min(limit, 100))

    published_matches = await search_published_catalog(
        session,
        tenant_id=tenant_id,
        query=cleaned_query,
        category=cleaned_category,
        status="active",
        limit=safe_limit,
    )
    if published_matches:
        models = [
            _published_match_to_catalog_item(match)
            for match in published_matches
        ]
        return CatalogListResult(
            category=cleaned_category,
            query=cleaned_query,
            total_results=len(models),
            models=models,
            source={
                "tool": "listCatalog",
                "catalog_runtime": "commercial_catalog_published",
            },
        )

    if await has_published_catalogs(session, tenant_id=tenant_id):
        return ToolNoDataResult(
            hint=(
                "published catalog has no active items for "
                f"category={cleaned_category!r} query={cleaned_query!r}"
            )
        )

    legacy_items = await _list_legacy_catalog_items(
        session=session,
        tenant_id=tenant_id,
        category=cleaned_category,
        query=cleaned_query,
        limit=safe_limit,
        collection_ids=collection_ids,
    )
    if not legacy_items:
        return ToolNoDataResult(
            hint=(
                "tenant has no catalog items for "
                f"category={cleaned_category!r} query={cleaned_query!r}"
            )
        )

    models = [_legacy_item_to_catalog_item(item) for item in legacy_items]
    return CatalogListResult(
        category=cleaned_category,
        query=cleaned_query,
        total_results=len(models),
        models=models,
        source={
            "tool": "listCatalog",
            "catalog_runtime": "tenant_catalogs_legacy",
        },
    )


def resolve_credit_plan(
    *,
    input_text: str,
    pipeline: PipelineDefinition,
    context: Mapping[str, Any] | None = None,
) -> CreditPlanResolutionResult | ToolNoDataResult:
    """Resolve customer text to the tenant's canonical credit selection key."""

    del context
    normalized_input = _normalize_lookup_key(input_text)
    if not normalized_input:
        return ToolNoDataResult(hint="empty credit-plan input")
    menu = build_credit_plan_menu(pipeline)
    if not menu:
        return ToolNoDataResult(hint="pipeline has no credit-plan selection aliases")
    option = resolve_credit_plan_option(input_text, pipeline)
    if option is None:
        return ToolNoDataResult(hint=f"could not resolve credit-plan input {input_text!r}")
    return _credit_plan_result(
        input_text=input_text,
        pipeline=pipeline,
        option=option,
        confidence=1.0 if normalized_input in {
            _normalize_lookup_key(alias) for alias in list(option.get("aliases") or [])
        } else 0.9,
    )


def get_missing_documents(
    *,
    pipeline: PipelineDefinition,
    state: Mapping[str, Any],
    selection_key: str | None = None,
) -> MissingDocumentsResult | ToolNoDataResult:
    """Return required/received/rejected/missing documents from current state."""

    attrs = _flatten_state_attrs(state)
    selection_field = pipeline.document_requirements_field
    resolved_selection = selection_key or _string_or_none(attrs.get(selection_field))

    requirements = lookup_requirements(
        pipeline=pipeline,
        selection_key=resolved_selection,
        customer_attrs=attrs,
    )
    if isinstance(requirements, ToolNoDataResult):
        return requirements

    return MissingDocumentsResult(
        selection_field=selection_field,
        selection_key=requirements.selection_key,
        selection_label=requirements.selection_label,
        required=requirements.required,
        received=requirements.received,
        rejected=requirements.rejected,
        missing=requirements.missing,
        complete=requirements.complete,
        source={
            "tool": "getMissingDocuments",
            "requirements_field": selection_field,
        },
    )


listCatalog = list_catalog  # noqa: N816 - public Knowledge Pack contract
resolveCreditPlan = resolve_credit_plan  # noqa: N816 - public Knowledge Pack contract
getMissingDocuments = get_missing_documents  # noqa: N816 - public Knowledge Pack contract


def _published_match_to_catalog_item(match: Any) -> CatalogListItem:
    raw = match.item if isinstance(match.item, Mapping) else {}
    cash_price = _decimal_or_zero(raw.get("base_price") or raw.get("cash_price_mxn"))
    list_price = _decimal_or_none(raw.get("list_price"))
    return CatalogListItem(
        sku=str(raw.get("sku") or ""),
        name=str(raw.get("name") or ""),
        category=str(raw.get("category") or ""),
        cash_price_mxn=cash_price,
        list_price_mxn=list_price,
        score=float(match.score),
        source={
            "catalog_id": str(match.catalog_id),
            "catalog_name": match.catalog_name,
            "vertical": match.vertical,
        },
    )


async def _list_legacy_catalog_items(
    *,
    session: AsyncSession,
    tenant_id: UUID,
    category: str | None,
    query: str,
    limit: int,
    collection_ids: list[UUID] | None,
) -> Sequence[TenantCatalogItem]:
    stmt = select(TenantCatalogItem).where(
        TenantCatalogItem.tenant_id == tenant_id,
        TenantCatalogItem.active.is_(True),
    )
    if category:
        stmt = stmt.where(func.lower(TenantCatalogItem.category) == category.lower())
    if query:
        needle = f"%{query.lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(TenantCatalogItem.sku).like(needle),
                func.lower(TenantCatalogItem.name).like(needle),
                func.lower(TenantCatalogItem.category).like(needle),
            )
        )
    if collection_ids:
        stmt = stmt.where(TenantCatalogItem.collection_id.in_(collection_ids))
    stmt = stmt.order_by(
        TenantCatalogItem.category.nulls_last(),
        TenantCatalogItem.name,
        TenantCatalogItem.sku,
    ).limit(limit)
    return (await session.execute(stmt)).scalars().all()


def _legacy_item_to_catalog_item(item: TenantCatalogItem) -> CatalogListItem:
    return CatalogListItem(
        sku=item.sku,
        name=item.name,
        category=item.category or "",
        cash_price_mxn=_decimal_or_zero(catalog_cash_price_mxn(item)),
        list_price_mxn=_decimal_or_none(catalog_list_price_mxn(item)),
        catalog_item_id=item.id,
        collection_id=item.collection_id,
        source={"catalog_runtime": "tenant_catalogs_legacy"},
    )


def _credit_plan_result(
    *,
    input_text: str,
    pipeline: PipelineDefinition,
    option: Mapping[str, Any],
    confidence: float,
) -> CreditPlanResolutionResult:
    field_name = pipeline.document_requirements_field
    field_updates = {
        str(key): str(value)
        for key, value in dict(option.get("field_updates") or {}).items()
        if str(key).strip() and value not in (None, "")
    }
    selection_key = str(option.get("selection_key") or "").strip()
    down_payment = str(option.get("down_payment") or option.get("plan") or "").strip() or None
    field_updates.setdefault(field_name, selection_key)
    if down_payment:
        field_updates["ENGANCHE"] = down_payment
    return CreditPlanResolutionResult(
        input=input_text,
        field_name=field_name,
        selection_key=selection_key,
        selection_label=str(option.get("selection_label") or selection_key).strip() or None,
        display_number=(
            int(option.get("display_number"))
            if str(option.get("display_number") or "").strip().isdigit()
            else None
        ),
        visible_label=str(option.get("visible_label") or option.get("menu_prompt") or "").strip()
        or None,
        down_payment=down_payment,
        requirements_key=str(option.get("requirements_key") or selection_key).strip() or None,
        matched_alias=input_text,
        confidence=confidence,
        field_updates=field_updates,
        source={
            "tool": "resolveCreditPlan",
            "alias_source": "credit_plan_menu",
        },
    )


def _flatten_state_attrs(state: Mapping[str, Any]) -> dict[str, Any]:
    raw_state: Any = state
    if hasattr(raw_state, "model_dump"):
        raw_state = raw_state.model_dump(mode="python")
    if isinstance(raw_state, Mapping) and isinstance(raw_state.get("state"), Mapping):
        raw_state = raw_state["state"]
    elif isinstance(raw_state, Mapping) and isinstance(raw_state.get("extracted_data"), Mapping):
        raw_state = raw_state["extracted_data"]

    attrs: dict[str, Any] = {}
    if not isinstance(raw_state, Mapping):
        return attrs
    for key, value in raw_state.items():
        if not isinstance(key, str):
            continue
        attrs[key] = _unwrap_extracted_value(value)
    return attrs


def _unwrap_extracted_value(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="python")
    if isinstance(value, Mapping) and "value" in value and "status" not in value:
        return deepcopy(value.get("value"))
    return deepcopy(value)


def _normalize_lookup_key(value: str) -> str:
    return normalize_whatsapp_text(value, keep_percent=False)


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return list(value)
    return [value]


def _string_or_none(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, Mapping):
        if "value" in value and len(value) <= 3:
            return _string_or_none(value.get("value"))
        return None
    text = str(value).strip()
    return text or None


def _decimal_or_zero(value: Any) -> Decimal:
    result = _decimal_or_none(value)
    return result if result is not None else Decimal("0")


def _decimal_or_none(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


__all__ = [
    "CatalogListItem",
    "CatalogListResult",
    "CreditPlanResolutionResult",
    "MissingDocumentsResult",
    "getMissingDocuments",
    "get_missing_documents",
    "listCatalog",
    "list_catalog",
    "resolveCreditPlan",
    "resolve_credit_plan",
]
