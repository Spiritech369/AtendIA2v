from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any


def _decimal_text(value: Any) -> str | None:
    if value is None or value == "":
        return None
    try:
        dec = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    text = format(dec, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def cents_to_mxn_text(cents: int | None) -> str | None:
    if cents is None:
        return None
    return _decimal_text(Decimal(cents) / Decimal("100"))


def normalize_text_list(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        parts = [part.strip() for part in raw.split(",")]
    elif isinstance(raw, (list, tuple, set)):
        parts = [str(item).strip() for item in raw if str(item).strip()]
    else:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in parts:
        lowered = item.casefold()
        if not lowered or lowered in seen:
            continue
        seen.add(lowered)
        out.append(item)
    return out


def _normalized_aliases(raw: Any, *, name: str, sku: str) -> list[str]:
    base = normalize_text_list(raw)
    extras = [name.strip(), sku.strip()]
    out: list[str] = []
    seen: set[str] = set()
    for item in [*base, *extras]:
        lowered = item.casefold()
        if not lowered or lowered in seen:
            continue
        seen.add(lowered)
        out.append(lowered)
    return out


def coerce_payment_plans(raw: Any) -> list[Any]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return deepcopy(raw)
    if not isinstance(raw, dict):
        return []
    out: list[Any] = []
    for key, value in raw.items():
        if isinstance(value, dict):
            plan = deepcopy(value)
            plan.setdefault("plan", str(key))
            out.append(plan)
        else:
            out.append({"plan": str(key), "value": deepcopy(value)})
    return out


def payment_options_from_plans(raw: Any) -> dict[str, Any]:
    plans = coerce_payment_plans(raw)
    out: dict[str, Any] = {}
    for index, item in enumerate(plans, start=1):
        if isinstance(item, dict):
            key = str(item.get("plan") or item.get("name") or item.get("id") or f"plan_{index}")
            out[key] = deepcopy(item)
        else:
            out[f"plan_{index}"] = deepcopy(item)
    return out


def build_catalog_attrs(
    *,
    base_attrs: dict[str, Any] | None,
    sku: str,
    name: str,
    category: str | None = None,
    price_cents: int | None = None,
    payment_plans: list[Any] | dict[str, Any] | None = None,
    source_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    attrs = deepcopy(base_attrs or {})

    if category and not isinstance(attrs.get("category"), str):
        attrs["category"] = category

    cash_price = (
        attrs.get("cash_price_mxn")
        or attrs.get("precio_contado_mxn")
        or attrs.get("precio_contado")
        or cents_to_mxn_text(price_cents)
    )
    if cash_price is not None:
        attrs["cash_price_mxn"] = _decimal_text(cash_price)

    list_price = (
        attrs.get("list_price_mxn")
        or attrs.get("precio_lista_mxn")
        or attrs.get("precio_lista")
    )
    if list_price is not None:
        attrs["list_price_mxn"] = _decimal_text(list_price)

    normalized_plans = coerce_payment_plans(
        payment_plans if payment_plans is not None else attrs.get("payment_plans")
    )
    if normalized_plans:
        attrs["payment_plans"] = normalized_plans
        attrs["payment_options"] = payment_options_from_plans(normalized_plans)

    if not isinstance(attrs.get("product_details"), dict) and isinstance(
        attrs.get("ficha_tecnica"), dict
    ):
        attrs["product_details"] = deepcopy(attrs["ficha_tecnica"])

    aliases = _normalized_aliases(
        attrs.get("alias") or attrs.get("aliases") or attrs.get("alias_normalizados"),
        name=name,
        sku=sku,
    )
    if aliases:
        attrs["alias"] = aliases
        attrs["aliases"] = aliases

    if source_meta:
        attrs["catalog_source"] = deepcopy(source_meta)

    return attrs


def catalog_cash_price_mxn(item: Any) -> Any:
    attrs = item.attrs or {}
    return (
        attrs.get("cash_price_mxn")
        or attrs.get("precio_contado_mxn")
        or attrs.get("precio_contado")
        or cents_to_mxn_text(getattr(item, "price_cents", None))
    )


def catalog_list_price_mxn(item: Any) -> Any:
    attrs = item.attrs or {}
    return (
        attrs.get("list_price_mxn")
        or attrs.get("precio_lista_mxn")
        or attrs.get("precio_lista")
        or catalog_cash_price_mxn(item)
    )


def catalog_payment_options(item: Any) -> dict[str, Any]:
    attrs = item.attrs or {}
    value = attrs.get("payment_options")
    if isinstance(value, dict):
        return deepcopy(value)
    value = attrs.get("planes_credito_normalizados")
    if isinstance(value, dict):
        return deepcopy(value)
    value = attrs.get("planes_credito")
    if isinstance(value, dict):
        return deepcopy(value)
    return payment_options_from_plans(getattr(item, "payment_plans", []))


def catalog_product_details(item: Any) -> dict[str, Any]:
    attrs = item.attrs or {}
    if isinstance(attrs.get("product_details"), dict):
        return deepcopy(attrs["product_details"])
    if isinstance(attrs.get("ficha_tecnica"), dict):
        return deepcopy(attrs["ficha_tecnica"])
    return {}


def catalog_has_quote_source(item: Any) -> bool:
    return catalog_cash_price_mxn(item) not in (None, "") or bool(catalog_payment_options(item))


def catalog_import_source_meta(
    *,
    document_id: str,
    filename: str,
    imported_at: datetime,
    source_version: str | None = None,
    source_name: str | None = None,
) -> dict[str, Any]:
    meta = {
        "document_id": document_id,
        "filename": filename,
        "imported_at": imported_at.isoformat(),
    }
    if source_version:
        meta["source_version"] = source_version
    if source_name:
        meta["source_name"] = source_name
    return meta
