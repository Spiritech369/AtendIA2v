from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


class CanonicalProductReference(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    product_id: str
    sku: str
    display_name: str | None = None
    catalog_id: str | None = None
    catalog_version_id: str | None = None
    evidence: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_identity(self) -> "CanonicalProductReference":
        if not self.product_id.strip():
            raise ValueError("product_id is required for canonical product references")
        if not self.sku.strip():
            raise ValueError("sku is required for canonical product references")
        return self


class CanonicalProduct(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    product_id: str
    sku: str
    display_name: str
    tenant_id: str | None = None
    catalog_id: str | None = None
    catalog_version_id: str | None = None
    product_type: str | None = None
    status: str = "active"
    aliases: list[str] = Field(default_factory=list)
    attributes: dict[str, Any] = Field(default_factory=dict)
    evidence: list[str] = Field(default_factory=list)

    def ref(self) -> CanonicalProductReference:
        return CanonicalProductReference(
            product_id=self.product_id,
            sku=self.sku,
            display_name=self.display_name,
            catalog_id=self.catalog_id,
            catalog_version_id=self.catalog_version_id,
            evidence=list(self.evidence),
        )


class AliasMap(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    aliases: dict[str, CanonicalProductReference] = Field(default_factory=dict)

    @classmethod
    def from_products(cls, products: list[CanonicalProduct]) -> "AliasMap":
        aliases: dict[str, CanonicalProductReference] = {}
        for product in products:
            ref = product.ref()
            for value in [product.display_name, product.sku, *product.aliases]:
                normalized = normalize_catalog_token(value)
                if normalized:
                    aliases[normalized] = ref
        return cls(aliases=aliases)

    def resolve(self, value: str) -> CanonicalProductReference | None:
        return self.aliases.get(normalize_catalog_token(value))


class SKUIndex(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    by_sku: dict[str, CanonicalProductReference] = Field(default_factory=dict)

    @classmethod
    def from_products(cls, products: list[CanonicalProduct]) -> "SKUIndex":
        return cls(
            by_sku={
                normalize_catalog_token(product.sku): product.ref()
                for product in products
                if normalize_catalog_token(product.sku)
            }
        )

    def resolve(self, sku: str) -> CanonicalProductReference | None:
        return self.by_sku.get(normalize_catalog_token(sku))


class QuoteSnapshot(BaseModel):
    """Immutable quote result produced by a trusted quote resolver."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    snapshot_id: str | None = None
    tenant_id: str
    product: CanonicalProductReference
    plan_id: str | None = None
    plan_code: str | None = None
    plan_name: str | None = None
    currency: str = "MXN"
    pricing: dict[str, Any] = Field(default_factory=dict)
    requirements: dict[str, Any] = Field(default_factory=dict)
    source_tool: str = "QuoteResolver"
    source_version: str | None = None
    quote_payload: dict[str, Any] = Field(default_factory=dict)
    evidence: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    integrity_hash: str | None = None

    @model_validator(mode="after")
    def validate_snapshot(self) -> "QuoteSnapshot":
        if not self.tenant_id.strip():
            raise ValueError("tenant_id is required")
        if not self.source_tool.strip():
            raise ValueError("source_tool is required")
        if not self.pricing and not self.quote_payload:
            raise ValueError("QuoteSnapshot requires pricing or quote_payload")
        if self.integrity_hash and self.integrity_hash != quote_snapshot_hash(self):
            raise ValueError("QuoteSnapshot integrity_hash mismatch")
        return self

    def with_integrity_hash(self) -> "QuoteSnapshot":
        return self.model_copy(update={"integrity_hash": quote_snapshot_hash(self)})


def quote_snapshot_hash(snapshot: QuoteSnapshot) -> str:
    payload = snapshot.model_dump(mode="json", exclude={"integrity_hash"})
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def normalize_catalog_token(value: Any) -> str:
    text = str(value or "").casefold().strip()
    normalized = unicodedata.normalize("NFD", text)
    folded = "".join(char for char in normalized if unicodedata.category(char) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", folded).strip()


def coerce_canonical_product_ref(value: Any) -> CanonicalProductReference | None:
    if isinstance(value, CanonicalProductReference):
        return value
    if not isinstance(value, dict):
        return None
    for key in ("canonical_product_ref", "product_ref", "product"):
        nested = value.get(key)
        if isinstance(nested, dict):
            return coerce_canonical_product_ref(nested)
    try:
        return CanonicalProductReference.model_validate(value)
    except (TypeError, ValueError, ValidationError):
        return None


def coerce_quote_snapshot(value: Any) -> QuoteSnapshot | None:
    if isinstance(value, QuoteSnapshot):
        return value
    if not isinstance(value, dict):
        return None
    try:
        return QuoteSnapshot.model_validate(value)
    except (TypeError, ValueError, ValidationError):
        return None


__all__ = [
    "AliasMap",
    "CanonicalProduct",
    "CanonicalProductReference",
    "QuoteSnapshot",
    "SKUIndex",
    "coerce_canonical_product_ref",
    "coerce_quote_snapshot",
    "normalize_catalog_token",
    "quote_snapshot_hash",
]
