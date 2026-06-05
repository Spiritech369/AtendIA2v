"""Translate a tenant-configured ``VisionResult`` into customer attr writes."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.contracts.pipeline_definition import PipelineDefinition
from atendia.contracts.vision_result import (
    RESERVED_NON_DOCUMENT_CATEGORIES,
    DocumentSide,
    VisionResult,
)
from atendia.db.models.customer import Customer
from atendia.db.models.customer_fields import CustomerFieldDefinition, CustomerFieldValue

_log = logging.getLogger(__name__)

ACCEPT_CONFIDENCE_FLOOR = 0.60


@dataclass(frozen=True)
class VisionDocWrite:
    """One customer attr write derived from image classification."""

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
    category: str,
    pipeline: PipelineDefinition,
    metadata: dict[str, Any],
    side: str | None,
) -> list[str]:
    """Resolve target customer attr keys from tenant configuration."""
    mapping = getattr(pipeline, "vision_doc_mapping", {}) or {}
    keys = list(mapping.get(category) or [])
    if not keys:
        return []
    if len(keys) == 1:
        return keys

    if side == DocumentSide.FRONT.value:
        return [keys[0]]
    if side == DocumentSide.BACK.value:
        return [keys[1]] if len(keys) > 1 else [keys[0]]
    if bool(metadata.get("both_sides")):
        return keys
    return [keys[0]]


def _decide_acceptance(
    vision_result: VisionResult,
) -> tuple[bool, str | None]:
    """Return (accepted, rejection_reason)."""
    qc = vision_result.quality_check
    confidence = float(vision_result.confidence)
    if qc is not None:
        if not qc.valid_for_file:
            reason = qc.rejection_reason or "image does not meet the configured quality criteria"
            return False, reason
        if confidence < ACCEPT_CONFIDENCE_FLOOR:
            return False, f"low confidence ({confidence:.0%})"
        return True, None

    legible = vision_result.metadata.get("legible")
    if confidence < ACCEPT_CONFIDENCE_FLOOR:
        return False, f"low confidence ({confidence:.0%})"
    if legible is False:
        return False, "the relevant information is not legible"
    return True, None


async def apply_vision_to_attrs(
    *,
    session: AsyncSession,
    customer_id: UUID | str,
    pipeline: PipelineDefinition,
    vision_result: VisionResult,
) -> list[VisionDocWrite]:
    """Apply configured document-category writes to ``customer.attrs``."""
    category = str(vision_result.category)
    if category in RESERVED_NON_DOCUMENT_CATEGORIES:
        return []

    metadata = vision_result.metadata if isinstance(vision_result.metadata, dict) else {}
    side = (
        vision_result.quality_check.side.value if vision_result.quality_check is not None else None
    )
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
