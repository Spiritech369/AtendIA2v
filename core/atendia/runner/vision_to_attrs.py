"""Fase 3 — translate a `VisionResult` into `customer.attrs` writes.

The runner calls `apply_vision_to_attrs` right after `classify_image()`
produces a `VisionResult`. We do two things:

  1. Decide accepted/rejected from `quality_check.valid_for_credit_file`
     (preferred) or, when the structured check is absent (legacy
     Vision output), fall back to the same heuristic that drives the
     Fase 1 document_event emitter.
  2. Look up which `customer.attrs[DOCS_X]` key(s) to write from
     `pipeline.vision_doc_mapping`. INE is the only multi-side doc;
     `metadata.ambos_lados` + `quality_check.side` drive the
     front/back disambiguation when the tenant configured the split.

Why a separate module from `ai_extraction_service`: NLU extractions
go through `decide_action` (AUTO vs SUGGEST vs SKIP) and a confidence
threshold ladder. Vision is different — the model has already done
the quality assessment, and the rejection_reason is the source of
truth (no SUGGEST path, no fuzzy confidence). Mixing the two would
muddle the behaviour the operator can reason about.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.contracts.pipeline_definition import PipelineDefinition
from atendia.contracts.vision_result import (
    DocumentSide,
    VisionCategory,
    VisionResult,
)
from atendia.db.models.customer import Customer
from atendia.db.models.customer_fields import CustomerFieldDefinition, CustomerFieldValue

_log = logging.getLogger(__name__)


# Categories that represent actual docs (vs moto / unrelated). The
# runner skips Vision-to-attrs for non-doc categories — moto = product
# photo, unrelated = off-topic; neither should ever mutate DOCS_*.
DOC_CATEGORIES: frozenset[VisionCategory] = frozenset(
    {
        VisionCategory.INE,
        VisionCategory.COMPROBANTE,
        VisionCategory.RECIBO_NOMINA,
        VisionCategory.ESTADO_CUENTA,
        VisionCategory.CONSTANCIA_SAT,
        VisionCategory.FACTURA,
        VisionCategory.IMSS,
    }
)

# Minimum confidence below which we treat the Vision output as
# "unsure" and skip the write, even if `valid_for_credit_file=true`.
# Mirrors the threshold the Fase 1 document_event emitter uses, so the
# two paths (event emission + attrs write) agree on what counts as
# "accepted".
ACCEPT_CONFIDENCE_FLOOR = 0.60


def _fold_text(value: str) -> str:
    return (
        value.casefold()
        .replace("á", "a")
        .replace("é", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ú", "u")
        .replace("ü", "u")
        .replace("ñ", "n")
    )


def _catalog_text(doc: Any) -> str:
    key = str(getattr(doc, "key", "") or "")
    label = str(getattr(doc, "label", "") or "")
    hint = str(getattr(doc, "hint", "") or "")
    return _fold_text(f"{key} {label} {hint}")


def _catalog_key(doc: Any) -> str | None:
    key = getattr(doc, "key", None)
    return key if isinstance(key, str) and key.startswith("DOCS_") else None


def _catalog_category_match(category: VisionCategory, text: str) -> bool:
    if category == VisionCategory.INE:
        return "ine" in text
    if category == VisionCategory.COMPROBANTE:
        return "comprobante" in text or "domicilio" in text
    if category == VisionCategory.RECIBO_NOMINA:
        return "recibo" in text and "nomina" in text
    if category == VisionCategory.ESTADO_CUENTA:
        return "estado" in text and "cuenta" in text
    if category == VisionCategory.CONSTANCIA_SAT:
        return "constancia" in text or "sat" in text
    if category == VisionCategory.FACTURA:
        return "factura" in text
    if category == VisionCategory.IMSS:
        return "imss" in text or "pension" in text
    return False


def _infer_doc_keys_from_catalog(
    *,
    category: VisionCategory,
    pipeline: PipelineDefinition,
    metadata: dict[str, Any],
    side: str | None,
) -> list[str]:
    matches: list[tuple[str, str]] = []
    for doc in getattr(pipeline, "documents_catalog", []) or []:
        key = _catalog_key(doc)
        if not key:
            continue
        text = _catalog_text(doc)
        if _catalog_category_match(category, text):
            matches.append((key, text))
    if not matches:
        return []
    if category != VisionCategory.INE or len(matches) == 1:
        return [matches[0][0]]

    front = [key for key, text in matches if re.search(r"\b(frente|front|delante)\b", text)]
    back = [key for key, text in matches if re.search(r"\b(atras|reverso|reverse|back)\b", text)]
    ambos_lados = bool(metadata.get("ambos_lados"))
    if side == DocumentSide.FRONT.value:
        return [front[0] if front else matches[0][0]]
    if side == DocumentSide.BACK.value:
        if back:
            return [back[0]]
        return [matches[1][0] if len(matches) > 1 else matches[0][0]]
    if ambos_lados:
        ordered = [*(front[:1] or [matches[0][0]]), *(back[:1] or [])]
        return list(dict.fromkeys(ordered or [key for key, _ in matches]))
    return [front[0] if front else matches[0][0]]


@dataclass(frozen=True)
class VisionDocWrite:
    """One DOCS_* key the runner wrote (or refused to write) on the
    customer.attrs as a result of a Vision call. Surfaced back to the
    runner so it can use the SAME decision when emitting the
    DOCUMENT_ACCEPTED / DOCUMENT_REJECTED system event — keeps the
    attrs row and the chat bubble from disagreeing.
    """

    doc_key: str
    accepted: bool
    rejection_reason: str | None
    confidence: float
    side: str | None


def _normalize_doc_value(
    accepted: bool,
    *,
    confidence: float,
    rejection_reason: str | None,
    side: str | None,
) -> dict[str, Any]:
    """Canonical shape for `customer.attrs[DOCS_X]` writes.

    This is the shape the `docs_complete_for_plan` evaluator reads
    (`<key>.status` == "ok"), and the shape `lookup_requirements`
    expects when reporting received vs rejected docs. Keep this
    in lockstep with both.
    """
    value: dict[str, Any] = {
        "status": "ok" if accepted else "rejected",
        "confidence": confidence,
        "verified_at": datetime.now(UTC).isoformat(),
        "source": "vision",
    }
    if not accepted and rejection_reason:
        value["rejection_reason"] = rejection_reason
    if side and side != DocumentSide.UNKNOWN.value:
        value["side"] = side
    return value


def _decide_doc_keys(
    *,
    category: VisionCategory,
    pipeline: PipelineDefinition,
    metadata: dict[str, Any],
    side: str | None,
) -> list[str]:
    """Resolve which DOCS_* keys to write from `pipeline.vision_doc_mapping`.

    The mapping ships per-tenant via the pipeline JSONB; an empty map
    means "this tenant doesn't auto-write — operator marks docs
    manually". We respect that by returning [] (the runner then skips).

    INE special-case: when a tenant maps "ine" to a 2-key list
    (frente + reverso), we use `side` + `ambos_lados` to pick the
    right subset:
      - side="front"  → first key only (DOCS_INE_FRENTE)
      - side="back"   → second key only (DOCS_INE_REVERSO)
      - side="unknown" + ambos_lados=true  → both keys
      - side="unknown" + ambos_lados=false → first key only (best guess)
    """
    keys = pipeline.vision_doc_mapping.get(category.value) or []
    if not keys:
        return []
    # Single-key mapping is the common case — comprobante, estado_cuenta,
    # etc. — no disambiguation needed.
    if len(keys) == 1:
        return list(keys)
    # Multi-key: only INE today. The mapping is opaque to this helper —
    # we treat keys[0] as "front side" and keys[1:] as "the rest"; the
    # tenant-side convention is documented in the seed.
    if category != VisionCategory.INE:
        # Unknown multi-key doc — write the first key as a safe default,
        # log so operators notice the mapping mismatch.
        _log.warning(
            "vision_doc_mapping for %s has >1 key but no side resolver; writing first key only",
            category.value,
        )
        return [keys[0]]
    ambos_lados = bool(metadata.get("ambos_lados"))
    if side == DocumentSide.FRONT.value:
        return [keys[0]]
    if side == DocumentSide.BACK.value:
        return [keys[1]] if len(keys) > 1 else [keys[0]]
    # side == unknown
    if ambos_lados:
        return list(keys)
    return [keys[0]]


def _decide_acceptance(
    vision_result: VisionResult,
) -> tuple[bool, str | None]:
    """Return (accepted, rejection_reason).

    Prefers the structured `quality_check.valid_for_credit_file` when
    present. Falls back to the legacy heuristic (`confidence >= 0.60`
    AND `metadata.legible != False`) so older Vision outputs without
    quality_check still produce a coherent decision.
    """
    qc = vision_result.quality_check
    confidence = float(vision_result.confidence)
    if qc is not None:
        if not qc.valid_for_credit_file:
            reason = qc.rejection_reason or "no cumple los criterios de calidad"
            return False, reason
        # Even with valid=true, drop if confidence is below the floor —
        # the LLM can be over-confident on edge cases (selfies of
        # documents at extreme angles); we'd rather ask again than
        # accept noise.
        if confidence < ACCEPT_CONFIDENCE_FLOOR:
            return False, f"confianza baja ({confidence:.0%})"
        return True, None
    # Legacy fallback — mirrors _emit_document_event_from_vision.
    legible = vision_result.metadata.get("legible")
    if confidence < ACCEPT_CONFIDENCE_FLOOR:
        return False, f"confianza baja ({confidence:.0%})"
    if legible is False:
        return False, "no se alcanzan a leer los datos del documento"
    return True, None


async def apply_vision_to_attrs(
    *,
    session: AsyncSession,
    customer_id: UUID | str,
    pipeline: PipelineDefinition,
    vision_result: VisionResult,
) -> list[VisionDocWrite]:
    """Translate a VisionResult into customer.attrs[DOCS_X] writes.

    Returns the list of writes the runner can use to emit matching
    DOCUMENT_ACCEPTED / DOCUMENT_REJECTED system events (Fase 1) and
    to refresh the contact panel. Returns [] when:
      - Vision returned a non-doc category (moto/unrelated).
      - Pipeline has no vision_doc_mapping entry for the category.
      - Customer row vanished (already deleted by another path).

    NEVER overwrites an existing `status='ok'` with `rejected` — once
    an operator (or this very helper) approved the doc, a later
    out-of-order resend of the same image shouldn't un-approve it.
    A NEW `status='ok'` always replaces an existing `rejected` though
    (the customer fixed the problem).
    """
    category = vision_result.category
    if category not in DOC_CATEGORIES:
        return []

    side = (
        vision_result.quality_check.side.value if vision_result.quality_check is not None else None
    )
    metadata = vision_result.metadata if isinstance(vision_result.metadata, dict) else {}

    doc_keys = _decide_doc_keys(
        category=category,
        pipeline=pipeline,
        metadata=metadata,
        side=side,
    )
    if not doc_keys:
        return []

    accepted, rejection_reason = _decide_acceptance(vision_result)

    customer = (
        await session.execute(select(Customer).where(Customer.id == customer_id))
    ).scalar_one_or_none()
    if customer is None:
        _log.warning("apply_vision_to_attrs: customer %s not found", customer_id)
        return []

    current_attrs: dict = dict(customer.attrs or {})
    next_attrs = dict(current_attrs)
    writes: list[VisionDocWrite] = []
    dirty = False

    for doc_key in doc_keys:
        existing = next_attrs.get(doc_key)
        existing_status: str | None = None
        if isinstance(existing, dict):
            existing_status = existing.get("status")
            if isinstance(existing_status, dict) and "value" in existing_status:
                existing_status = existing_status["value"]
        elif existing is True:
            existing_status = "ok"
        elif isinstance(existing, str):
            existing_status = existing.lower()

        # Don't downgrade an already-accepted doc on a later rejected
        # resend. The composer can still acknowledge with a message,
        # but the structural state stays approved.
        if not accepted and existing_status == "ok":
            writes.append(
                VisionDocWrite(
                    doc_key=doc_key,
                    accepted=False,
                    rejection_reason=rejection_reason,
                    confidence=float(vision_result.confidence),
                    side=side,
                )
            )
            continue

        next_attrs[doc_key] = _normalize_doc_value(
            accepted,
            confidence=float(vision_result.confidence),
            rejection_reason=rejection_reason,
            side=side,
        )
        dirty = True
        writes.append(
            VisionDocWrite(
                doc_key=doc_key,
                accepted=accepted,
                rejection_reason=rejection_reason,
                confidence=float(vision_result.confidence),
                side=side,
            )
        )

    if dirty:
        customer.attrs = next_attrs
        session.add(customer)
        await _sync_configured_customer_field(
            session=session,
            customer=customer,
            doc_keys=[write.doc_key for write in writes],
            accepted=accepted,
        )

    return writes


async def _sync_configured_customer_field(
    *,
    session: AsyncSession,
    customer: Customer,
    doc_keys: list[str],
    accepted: bool,
) -> None:
    tenant_id = getattr(customer, "tenant_id", None)
    customer_id = getattr(customer, "id", None)
    if tenant_id is None or customer_id is None or not doc_keys:
        return
    try:
        result = await session.execute(
            select(CustomerFieldDefinition).where(
                CustomerFieldDefinition.tenant_id == tenant_id,
                or_(
                    CustomerFieldDefinition.key.in_(doc_keys),
                    func.upper(CustomerFieldDefinition.key).in_(doc_keys),
                ),
            )
        )
    except Exception:
        _log.exception("failed to load configured customer fields for doc sync")
        return

    if not hasattr(result, "scalars"):
        return
    definitions = list(result.scalars().all())
    for definition in definitions:
        value = "true" if accepted else "false"
        if definition.field_type not in {"checkbox", "text", "select"}:
            continue
        if definition.field_type in {"text", "select"}:
            value = "ok" if accepted else "rejected"
        existing = (
            await session.execute(
                select(CustomerFieldValue).where(
                    CustomerFieldValue.customer_id == customer_id,
                    CustomerFieldValue.field_definition_id == definition.id,
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            session.add(
                CustomerFieldValue(
                    customer_id=customer_id,
                    field_definition_id=definition.id,
                    value=value,
                )
            )
        else:
            existing.value = value
