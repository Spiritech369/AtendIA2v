"""Pure-function tests for lookup_requirements.

The tool reads a PipelineDefinition + customer attrs dict and returns a
RequirementsResult / ToolNoDataResult. No DB, no LLM — so the tests
build small in-memory pipeline objects via Pydantic constructors and
assert the structured outputs the composer will consume.

If you change the RequirementsResult shape (received/rejected/missing
buckets, complete flag), this file is the canary — the composer prompt
relies on the same field names.
"""

from __future__ import annotations

from atendia.contracts.pipeline_definition import (
    DocumentSpec,
    PipelineDefinition,
    StageDefinition,
)
from atendia.tools.base import ToolNoDataResult
from atendia.tools.lookup_requirements import (
    RequiredDoc,
    RequirementsResult,
    lookup_requirements,
)


def _make_pipeline(
    docs_per_plan: dict[str, list[str]] | None = None,
    catalog: list[DocumentSpec] | None = None,
) -> PipelineDefinition:
    """A minimal valid PipelineDefinition for the tool under test."""
    return PipelineDefinition(
        version=1,
        stages=[
            StageDefinition(id="nuevo", actions_allowed=["ask_field"]),
        ],
        fallback="ask_clarification",
        docs_per_plan=docs_per_plan or {},
        documents_catalog=catalog or [],
    )


def test_returns_no_data_when_plan_credito_missing():
    pipeline = _make_pipeline(
        docs_per_plan={"nomina_tarjeta_10": ["DOCS_INE"]},
    )
    result = lookup_requirements(
        pipeline=pipeline,
        plan_credito=None,
        customer_attrs={},
    )
    assert isinstance(result, ToolNoDataResult)
    assert "plan_credito" in result.hint


def test_returns_no_data_when_plan_not_in_catalog():
    pipeline = _make_pipeline(
        docs_per_plan={"nomina_tarjeta_10": ["DOCS_INE"]},
    )
    result = lookup_requirements(
        pipeline=pipeline,
        plan_credito="some_unknown_plan",
        customer_attrs={},
    )
    assert isinstance(result, ToolNoDataResult)


def test_returns_no_data_when_plan_has_empty_doc_list():
    """An operator that defined the plan but left the doc list empty
    should not produce 'no documentos requeridos' — we'd rather signal
    no_data so the composer redirects."""
    pipeline = _make_pipeline(docs_per_plan={"sin_comprobantes_25": []})
    result = lookup_requirements(
        pipeline=pipeline,
        plan_credito="sin_comprobantes_25",
        customer_attrs={},
    )
    assert isinstance(result, ToolNoDataResult)


def test_all_missing_when_customer_has_no_docs():
    pipeline = _make_pipeline(
        docs_per_plan={
            "nomina_tarjeta_10": ["DOCS_INE", "DOCS_COMPROBANTE", "DOCS_ESTADO_CUENTA"],
        },
        catalog=[
            DocumentSpec(key="DOCS_INE", label="INE por ambos lados"),
            DocumentSpec(key="DOCS_COMPROBANTE", label="Comprobante de domicilio"),
            DocumentSpec(key="DOCS_ESTADO_CUENTA", label="Estados de cuenta"),
        ],
    )
    result = lookup_requirements(
        pipeline=pipeline,
        plan_credito="nomina_tarjeta_10",
        customer_attrs={},
    )
    assert isinstance(result, RequirementsResult)
    assert result.plan_key == "nomina_tarjeta_10"
    assert len(result.required) == 3
    assert len(result.missing) == 3
    assert result.received == []
    assert result.rejected == []
    assert result.complete is False


def test_received_when_doc_status_is_ok():
    pipeline = _make_pipeline(
        docs_per_plan={"nomina_tarjeta_10": ["DOCS_INE", "DOCS_COMPROBANTE"]},
        catalog=[
            DocumentSpec(key="DOCS_INE", label="INE"),
            DocumentSpec(key="DOCS_COMPROBANTE", label="Comprobante"),
        ],
    )
    result = lookup_requirements(
        pipeline=pipeline,
        plan_credito="nomina_tarjeta_10",
        customer_attrs={
            "DOCS_INE": {"status": "ok"},
            # DOCS_COMPROBANTE absent → missing
        },
    )
    assert isinstance(result, RequirementsResult)
    assert [d.key for d in result.received] == ["DOCS_INE"]
    assert [d.key for d in result.missing] == ["DOCS_COMPROBANTE"]
    assert result.complete is False


def test_accepts_plain_boolean_true_as_ok_legacy_shape():
    """Operators editing the contact panel write `DOCS_INE: true` directly.
    The tool tolerates this so manual flows don't appear stuck on missing."""
    pipeline = _make_pipeline(
        docs_per_plan={"plan_x": ["DOCS_INE"]},
        catalog=[DocumentSpec(key="DOCS_INE", label="INE")],
    )
    result = lookup_requirements(
        pipeline=pipeline,
        plan_credito="plan_x",
        customer_attrs={"DOCS_INE": True},
    )
    assert isinstance(result, RequirementsResult)
    assert result.received[0].key == "DOCS_INE"
    assert result.complete is True


def test_rejected_carries_reason():
    pipeline = _make_pipeline(
        docs_per_plan={"plan_x": ["DOCS_INE"]},
        catalog=[DocumentSpec(key="DOCS_INE", label="INE")],
    )
    result = lookup_requirements(
        pipeline=pipeline,
        plan_credito="plan_x",
        customer_attrs={
            "DOCS_INE": {
                "status": "rejected",
                "rejection_reason": "se ve con reflejo",
            },
        },
    )
    assert isinstance(result, RequirementsResult)
    assert result.received == []
    assert len(result.rejected) == 1
    rejected_doc = result.rejected[0]
    assert rejected_doc.rejection_reason == "se ve con reflejo"
    # complete is False even though nothing is 'missing' — rejected
    # docs are not "still pending" but they are NOT acceptable.
    assert result.complete is False


def test_complete_when_all_docs_have_ok_status():
    pipeline = _make_pipeline(
        docs_per_plan={"plan_x": ["DOCS_INE", "DOCS_COMPROBANTE"]},
        catalog=[
            DocumentSpec(key="DOCS_INE", label="INE"),
            DocumentSpec(key="DOCS_COMPROBANTE", label="Comprobante"),
        ],
    )
    result = lookup_requirements(
        pipeline=pipeline,
        plan_credito="plan_x",
        customer_attrs={
            "DOCS_INE": {"status": "ok"},
            "DOCS_COMPROBANTE": {"status": "ok"},
        },
    )
    assert isinstance(result, RequirementsResult)
    assert result.complete is True
    assert result.missing == []
    assert result.rejected == []
    assert len(result.received) == 2


def test_missing_when_catalog_lacks_entry_falls_back_to_raw_key():
    """A doc key referenced in docs_per_plan but not declared in the
    catalog should still render — using the raw key as label. This
    keeps tenants who edit JSON manually from getting empty labels."""
    pipeline = _make_pipeline(
        docs_per_plan={"plan_x": ["DOCS_RECIBO_NOMINA"]},
        # Note: no DocumentSpec for DOCS_RECIBO_NOMINA
    )
    result = lookup_requirements(
        pipeline=pipeline,
        plan_credito="plan_x",
        customer_attrs={},
    )
    assert isinstance(result, RequirementsResult)
    assert result.missing[0].label == "DOCS_RECIBO_NOMINA"


def test_unwraps_extracted_data_shape():
    """customer.attrs sometimes stores values in the
    {value, confidence} shape inherited from NLU. The tool should
    unwrap that for the status field too — mirrors the pipeline_evaluator
    behavior for docs_complete_for_plan."""
    pipeline = _make_pipeline(
        docs_per_plan={"plan_x": ["DOCS_INE"]},
        catalog=[DocumentSpec(key="DOCS_INE", label="INE")],
    )
    result = lookup_requirements(
        pipeline=pipeline,
        plan_credito="plan_x",
        customer_attrs={
            "DOCS_INE": {"status": {"value": "ok", "confidence": 0.9}},
        },
    )
    assert isinstance(result, RequirementsResult)
    assert result.complete is True


def test_required_doc_pydantic_round_trip():
    """The composer serializes `action_payload` via .model_dump(mode='json').
    Ensure RequiredDoc / RequirementsResult survive that."""
    pipeline = _make_pipeline(
        docs_per_plan={"plan_x": ["DOCS_INE"]},
        catalog=[DocumentSpec(key="DOCS_INE", label="INE")],
    )
    result = lookup_requirements(
        pipeline=pipeline,
        plan_credito="plan_x",
        customer_attrs={},
    )
    assert isinstance(result, RequirementsResult)
    dumped = result.model_dump(mode="json")
    assert dumped["status"] == "ok"
    assert dumped["plan_key"] == "plan_x"
    assert dumped["missing"][0]["key"] == "DOCS_INE"
    # Round-trip
    restored = RequirementsResult.model_validate(dumped)
    assert restored == result
    # And RequiredDoc alone
    rd = RequiredDoc(key="DOCS_INE", label="INE", status="missing")
    assert RequiredDoc.model_validate(rd.model_dump(mode="json")) == rd
