"""Unit tests for apply_vision_to_attrs (Fase 3).

The helper is pure-ish — it reads VisionResult + pipeline + customer
attrs and emits writes. We use a fake session that records `.add()`
plus a stub customer object so the test surface stays focused on the
decision logic (no DB round-trip).

If the canonical attrs shape changes (status / confidence / verified_at
/ rejection_reason / side keys), this file is the canary.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from atendia.contracts.pipeline_definition import (
    DocumentSpec,
    PipelineDefinition,
    StageDefinition,
)
from atendia.contracts.vision_result import (
    DocumentSide,
    VisionCategory,
    VisionQualityCheck,
    VisionResult,
)
from atendia.runner.vision_to_attrs import (
    ACCEPT_CONFIDENCE_FLOOR,
    DOC_CATEGORIES,
    apply_vision_to_attrs,
)


# ---------------------------------------------------------------------------
# Fixtures: in-memory pipeline + a fake customer/session pair so we don't
# need a DB to assert the helper's behaviour.
# ---------------------------------------------------------------------------


_DEFAULT_MAPPING: dict[str, list[str]] = {
    "ine": ["DOCS_INE_FRENTE", "DOCS_INE_REVERSO"],
    "comprobante": ["DOCS_COMPROBANTE"],
}


def _make_pipeline(mapping: dict[str, list[str]] | None = None) -> PipelineDefinition:
    # `mapping is None` means "use the test default"; passing `{}`
    # explicitly tests the empty-mapping branch — distinguishing the two
    # with `or` would shadow the empty-dict case.
    resolved = _DEFAULT_MAPPING if mapping is None else mapping
    return PipelineDefinition(
        version=1,
        stages=[StageDefinition(id="nuevo", actions_allowed=["ask_field"])],
        fallback="ask_clarification",
        documents_catalog=[
            DocumentSpec(key="DOCS_INE_FRENTE", label="INE frente"),
            DocumentSpec(key="DOCS_INE_REVERSO", label="INE reverso"),
            DocumentSpec(key="DOCS_COMPROBANTE", label="Comprobante"),
        ],
        vision_doc_mapping=resolved,
    )


class _FakeSession:
    def __init__(self, customer_attrs: dict[str, Any] | None = None) -> None:
        self.customer = MagicMock()
        self.customer.id = uuid4()
        self.customer.attrs = dict(customer_attrs or {})
        self.added: list[Any] = []

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def execute(self, _stmt: Any) -> Any:
        # apply_vision_to_attrs only does session.execute(...) for the
        # customer lookup; return a scalar-shaped result.
        return _FakeExecuteResult(self.customer)


class _FakeExecuteResult:
    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar_one_or_none(self) -> Any:
        return self._value


def _ok_qc(side: DocumentSide = DocumentSide.FRONT) -> VisionQualityCheck:
    return VisionQualityCheck(
        four_corners_visible=True,
        legible=True,
        not_blurry=True,
        no_flash_glare=True,
        not_cut=True,
        side=side,
        valid_for_credit_file=True,
        rejection_reason=None,
    )


def _bad_qc(reason: str) -> VisionQualityCheck:
    return VisionQualityCheck(
        four_corners_visible=False,
        legible=False,
        not_blurry=False,
        no_flash_glare=False,
        not_cut=True,
        side=DocumentSide.UNKNOWN,
        valid_for_credit_file=False,
        rejection_reason=reason,
    )


# ---------------------------------------------------------------------------
# Pure decision tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_skips_non_doc_categories():
    """moto / unrelated should never produce a write — they're not docs."""
    pipeline = _make_pipeline()
    session = _FakeSession()
    for cat in (VisionCategory.MOTO, VisionCategory.UNRELATED):
        result = VisionResult(category=cat, confidence=0.95, metadata={})
        writes = await apply_vision_to_attrs(
            session=session, customer_id=session.customer.id,
            pipeline=pipeline, vision_result=result,
        )
        assert writes == []
    assert session.added == []


@pytest.mark.asyncio
async def test_skips_when_mapping_empty():
    """A tenant with no vision_doc_mapping configured stays in manual mode."""
    pipeline = _make_pipeline(mapping={})
    session = _FakeSession()
    result = VisionResult(
        category=VisionCategory.COMPROBANTE,
        confidence=0.9, metadata={}, quality_check=_ok_qc(),
    )
    writes = await apply_vision_to_attrs(
        session=session, customer_id=session.customer.id,
        pipeline=pipeline, vision_result=result,
    )
    assert writes == []


@pytest.mark.asyncio
async def test_writes_ok_status_for_accepted_doc():
    """Happy path — comprobante accepted, status='ok' lands on attrs."""
    pipeline = _make_pipeline()
    session = _FakeSession()
    result = VisionResult(
        category=VisionCategory.COMPROBANTE,
        confidence=0.92,
        metadata={"legible": True, "ambos_lados": False, "fecha_iso": None,
                  "institucion": "CFE", "modelo": None, "notas": None},
        quality_check=_ok_qc(side=DocumentSide.UNKNOWN),
    )
    writes = await apply_vision_to_attrs(
        session=session, customer_id=session.customer.id,
        pipeline=pipeline, vision_result=result,
    )
    assert len(writes) == 1
    assert writes[0].doc_key == "DOCS_COMPROBANTE"
    assert writes[0].accepted is True
    assert writes[0].rejection_reason is None
    # Customer.attrs got mutated with the canonical shape.
    written = session.customer.attrs["DOCS_COMPROBANTE"]
    assert written["status"] == "ok"
    assert written["source"] == "vision"
    assert written["confidence"] == pytest.approx(0.92)
    assert "verified_at" in written
    assert "rejection_reason" not in written


@pytest.mark.asyncio
async def test_writes_rejected_with_reason_from_quality_check():
    pipeline = _make_pipeline()
    session = _FakeSession()
    result = VisionResult(
        category=VisionCategory.COMPROBANTE,
        confidence=0.85,
        metadata={},
        quality_check=_bad_qc("se ve con reflejo, no se leen los datos"),
    )
    writes = await apply_vision_to_attrs(
        session=session, customer_id=session.customer.id,
        pipeline=pipeline, vision_result=result,
    )
    assert len(writes) == 1
    assert writes[0].accepted is False
    assert "reflejo" in writes[0].rejection_reason
    assert session.customer.attrs["DOCS_COMPROBANTE"]["status"] == "rejected"
    assert (
        session.customer.attrs["DOCS_COMPROBANTE"]["rejection_reason"]
        == "se ve con reflejo, no se leen los datos"
    )


@pytest.mark.asyncio
async def test_low_confidence_forces_reject_even_when_qc_says_valid():
    """Anti-overconfidence: the QC can claim valid=true while the
    overall confidence is below the floor (model unsure)."""
    pipeline = _make_pipeline()
    session = _FakeSession()
    result = VisionResult(
        category=VisionCategory.COMPROBANTE,
        confidence=ACCEPT_CONFIDENCE_FLOOR - 0.01,
        metadata={}, quality_check=_ok_qc(),
    )
    writes = await apply_vision_to_attrs(
        session=session, customer_id=session.customer.id,
        pipeline=pipeline, vision_result=result,
    )
    assert writes[0].accepted is False
    assert "confianza baja" in writes[0].rejection_reason


# ---------------------------------------------------------------------------
# INE multi-side disambiguation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ine_front_writes_only_front_key():
    pipeline = _make_pipeline()
    session = _FakeSession()
    result = VisionResult(
        category=VisionCategory.INE,
        confidence=0.95,
        metadata={"ambos_lados": False},
        quality_check=_ok_qc(side=DocumentSide.FRONT),
    )
    writes = await apply_vision_to_attrs(
        session=session, customer_id=session.customer.id,
        pipeline=pipeline, vision_result=result,
    )
    assert [w.doc_key for w in writes] == ["DOCS_INE_FRENTE"]
    assert "DOCS_INE_FRENTE" in session.customer.attrs
    assert "DOCS_INE_REVERSO" not in session.customer.attrs


@pytest.mark.asyncio
async def test_ine_back_writes_only_back_key():
    pipeline = _make_pipeline()
    session = _FakeSession()
    result = VisionResult(
        category=VisionCategory.INE,
        confidence=0.95,
        metadata={"ambos_lados": False},
        quality_check=_ok_qc(side=DocumentSide.BACK),
    )
    writes = await apply_vision_to_attrs(
        session=session, customer_id=session.customer.id,
        pipeline=pipeline, vision_result=result,
    )
    assert [w.doc_key for w in writes] == ["DOCS_INE_REVERSO"]


@pytest.mark.asyncio
async def test_ine_unknown_with_ambos_lados_writes_both_keys():
    pipeline = _make_pipeline()
    session = _FakeSession()
    result = VisionResult(
        category=VisionCategory.INE,
        confidence=0.95,
        metadata={"ambos_lados": True},
        quality_check=_ok_qc(side=DocumentSide.UNKNOWN),
    )
    writes = await apply_vision_to_attrs(
        session=session, customer_id=session.customer.id,
        pipeline=pipeline, vision_result=result,
    )
    assert {w.doc_key for w in writes} == {"DOCS_INE_FRENTE", "DOCS_INE_REVERSO"}
    assert "DOCS_INE_FRENTE" in session.customer.attrs
    assert "DOCS_INE_REVERSO" in session.customer.attrs


@pytest.mark.asyncio
async def test_ine_unknown_no_ambos_lados_writes_front_only():
    pipeline = _make_pipeline()
    session = _FakeSession()
    result = VisionResult(
        category=VisionCategory.INE,
        confidence=0.95,
        metadata={"ambos_lados": False},
        quality_check=_ok_qc(side=DocumentSide.UNKNOWN),
    )
    writes = await apply_vision_to_attrs(
        session=session, customer_id=session.customer.id,
        pipeline=pipeline, vision_result=result,
    )
    assert [w.doc_key for w in writes] == ["DOCS_INE_FRENTE"]


# ---------------------------------------------------------------------------
# Idempotency / overwrite guard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_does_not_downgrade_existing_ok_to_rejected():
    """If the customer already had status='ok' from an earlier accepted
    image, a later rejected resend does NOT clobber that. The chat
    bubble still fires (operator sees the rejection), but the structural
    state stays approved."""
    pipeline = _make_pipeline()
    session = _FakeSession(customer_attrs={
        "DOCS_COMPROBANTE": {
            "status": "ok",
            "confidence": 0.9,
            "verified_at": "2026-05-13T22:00:00+00:00",
            "source": "vision",
        },
    })
    result = VisionResult(
        category=VisionCategory.COMPROBANTE,
        confidence=0.85,
        metadata={}, quality_check=_bad_qc("borrosa"),
    )
    writes = await apply_vision_to_attrs(
        session=session, customer_id=session.customer.id,
        pipeline=pipeline, vision_result=result,
    )
    assert writes[0].accepted is False  # event still says rejected
    assert session.customer.attrs["DOCS_COMPROBANTE"]["status"] == "ok"


@pytest.mark.asyncio
async def test_accepts_resend_overwrites_previous_rejection():
    """Inverse case: rejected → accepted resend SHOULD overwrite."""
    pipeline = _make_pipeline()
    session = _FakeSession(customer_attrs={
        "DOCS_COMPROBANTE": {
            "status": "rejected",
            "rejection_reason": "se cortó una esquina",
            "confidence": 0.4,
            "verified_at": "2026-05-13T22:00:00+00:00",
            "source": "vision",
        },
    })
    result = VisionResult(
        category=VisionCategory.COMPROBANTE,
        confidence=0.93,
        metadata={}, quality_check=_ok_qc(),
    )
    writes = await apply_vision_to_attrs(
        session=session, customer_id=session.customer.id,
        pipeline=pipeline, vision_result=result,
    )
    assert writes[0].accepted is True
    final = session.customer.attrs["DOCS_COMPROBANTE"]
    assert final["status"] == "ok"
    assert "rejection_reason" not in final


# ---------------------------------------------------------------------------
# Legacy back-compat (Vision without quality_check)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_legacy_vision_without_quality_check_falls_back_to_heuristic():
    pipeline = _make_pipeline()
    session = _FakeSession()
    result = VisionResult(
        category=VisionCategory.COMPROBANTE,
        confidence=0.91,
        metadata={"legible": True},
        quality_check=None,  # legacy / older prompt
    )
    writes = await apply_vision_to_attrs(
        session=session, customer_id=session.customer.id,
        pipeline=pipeline, vision_result=result,
    )
    assert writes[0].accepted is True


@pytest.mark.asyncio
async def test_legacy_vision_with_illegible_metadata_rejects():
    pipeline = _make_pipeline()
    session = _FakeSession()
    result = VisionResult(
        category=VisionCategory.COMPROBANTE,
        confidence=0.91,
        metadata={"legible": False},
        quality_check=None,
    )
    writes = await apply_vision_to_attrs(
        session=session, customer_id=session.customer.id,
        pipeline=pipeline, vision_result=result,
    )
    assert writes[0].accepted is False
    # Either the structured "ilegible" wording or the legacy
    # "no se ... leer" phrasing — both signal the same thing to the operator.
    reason = writes[0].rejection_reason.lower()
    assert "ilegible" in reason or "leer" in reason


def test_doc_categories_only_includes_real_documents():
    """The frozenset is the source of truth for `which categories are
    treated as docs`. Adding moto/unrelated here would auto-trigger
    DOCS_* writes for product photos — break loudly."""
    assert VisionCategory.MOTO not in DOC_CATEGORIES
    assert VisionCategory.UNRELATED not in DOC_CATEGORIES
    # Sanity — every other category IS a doc.
    for cat in VisionCategory:
        if cat not in {VisionCategory.MOTO, VisionCategory.UNRELATED}:
            assert cat in DOC_CATEGORIES
