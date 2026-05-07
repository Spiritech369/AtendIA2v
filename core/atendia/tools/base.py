from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession


class ToolNotFoundError(Exception):
    """Raised when a tool name is not in the registry."""


class Tool(ABC):
    name: str

    @abstractmethod
    async def run(self, session: AsyncSession, **kwargs: Any) -> dict:
        ...


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
    """Real-data result from `quote(sku=...)`.

    `Quote` is the rich shape: full price ladder, planes de crédito, and
    ficha técnica — everything the Composer prompt needs to write a single
    accurate WhatsApp message without a second tool call.

    Status is a fixed literal so the Composer router branches on
    `payload["status"] == "ok"` without isinstance checks.
    """
    status: Literal["ok"] = "ok"
    sku: str
    name: str
    category: str
    price_lista_mxn: Decimal
    price_contado_mxn: Decimal
    planes_credito: dict
    ficha_tecnica: dict


class FAQMatch(BaseModel):
    """Single FAQ hit with its raw cosine similarity.

    Returned inside `lookup_faq()`'s response list. `score` is in [0, 1]
    (1 = identical embedding); the runner applies the design-doc threshold
    `score >= 0.5` before forwarding to Composer.
    """
    pregunta: str
    respuesta: str
    score: float


class CatalogResult(BaseModel):
    """One row of `search_catalog()`'s ranked list.

    Lighter than `Quote` — no `planes_credito` or `ficha_tecnica` because
    `search_catalog` is the browsing entry point ("muéstrame motonetas
    económicas"). Once the user picks one, the runner re-dispatches to
    `quote(sku=…)` for the full payload.
    """
    sku: str
    name: str
    category: str
    price_contado_mxn: Decimal
    score: float
