from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import AliasChoices, BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession


class ToolNotFoundError(Exception):
    """Raised when a tool name is not in the registry."""


class Tool(ABC):
    name: str

    @abstractmethod
    async def run(self, session: AsyncSession, **kwargs: Any) -> dict: ...


class ToolNoDataResult(BaseModel):
    """Returned (or constructed) when a tool can't produce real data yet.

    Used by Phase 3b's Composer pathway for actions like `quote` / `lookup_faq` /
    `search_catalog` when the tenant catalog or FAQs are not populated. The
    Composer's prompt receives `hint` and is instructed to redirect rather than
    invent data.

    Phase 3c will populate the catalog/FAQs and tools will start returning real
    data; ToolNoDataResult will become the rare error path then.
    """

    status: Literal["no_data"] = "no_data"
    hint: str


# ---------------------------------------------------------------------------
# Phase 3c.1 result models — emitted when tools find real data.
# Composer's `action_payload` switches on `status`: "ok" (Quote) → use the
# data; "no_data" (ToolNoDataResult) → redirect.
# ---------------------------------------------------------------------------


class Quote(BaseModel):
    """Structured result from ``quote(sku=...)``.

    The shape is product-neutral: list/cash price, payment options and
    product details. Tenant-specific names or old catalog keys are handled
    outside the runtime surface.
    """

    model_config = ConfigDict(populate_by_name=True)

    status: Literal["ok"] = "ok"
    sku: str
    name: str
    category: str
    list_price_mxn: Decimal = Field(
        validation_alias=AliasChoices("list_price_mxn", "price_lista_mxn")
    )
    cash_price_mxn: Decimal = Field(
        validation_alias=AliasChoices("cash_price_mxn", "price_contado_mxn", "precio_contado_mxn")
    )
    payment_options: dict = Field(
        validation_alias=AliasChoices("payment_options", "planes_credito")
    )
    product_details: dict = Field(validation_alias=AliasChoices("product_details", "ficha_tecnica"))
    source: dict = Field(default_factory=dict)

    @property
    def price_lista_mxn(self) -> Decimal:
        return self.list_price_mxn

    @property
    def precio_contado_mxn(self) -> Decimal:
        return self.cash_price_mxn

    @property
    def price_contado_mxn(self) -> Decimal:
        return self.cash_price_mxn

    @property
    def planes_credito(self) -> dict:
        return self.payment_options

    @property
    def ficha_tecnica(self) -> dict:
        return self.product_details


class FAQMatch(BaseModel):
    """Single FAQ hit with its raw cosine similarity.

    Returned inside `lookup_faq()`'s response list. `score` is in [0, 1]
    (1 = identical embedding); the runner applies the design-doc threshold
    `score >= 0.5` before forwarding to Composer.

    `faq_id` and `collection_id` (migration 045) let the DebugPanel
    deep-link each hit back to the KB module so the operator can edit the
    source row in one click. Both nullable because some providers do not
    expose editable source rows.
    """

    pregunta: str
    respuesta: str
    score: float
    faq_id: UUID | None = None
    collection_id: UUID | None = None


class CatalogResult(BaseModel):
    """One row of `search_catalog()`'s ranked list.

    Lighter than `Quote`; `search_catalog` is the browsing entry point
    for product or service discovery. Once the user picks one, the
    runner can re-dispatch to `quote(sku=...)` for the full payload.

    `catalog_item_id` and `collection_id` (migration 045) enable
    DebugPanel deep-links the same way as FAQMatch.
    """

    model_config = ConfigDict(populate_by_name=True)

    sku: str
    name: str
    category: str
    cash_price_mxn: Decimal = Field(
        validation_alias=AliasChoices("cash_price_mxn", "price_contado_mxn", "precio_contado_mxn")
    )
    score: float
    catalog_item_id: UUID | None = None
    collection_id: UUID | None = None
    source: dict = Field(default_factory=dict)

    @property
    def price_contado_mxn(self) -> Decimal:
        return self.cash_price_mxn
