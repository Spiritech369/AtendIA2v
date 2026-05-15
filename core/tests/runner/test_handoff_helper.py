"""Tests for handoff_helper (Phase 3c.2 / T24)."""

import json

from atendia.contracts.extracted_fields import (
    ExtractedFields,
    PlanCredito,
    TipoCredito,
)
from atendia.contracts.handoff_summary import HandoffReason
from atendia.runner.handoff_helper import build_handoff_summary

_DOCS_PER_PLAN = {
    "Nómina Tarjeta": ["ine", "comprobante", "estados_de_cuenta", "nomina"],
    "Sin Comprobantes": ["ine", "comprobante"],
}


def test_build_handoff_summary_complete_flow() -> None:
    """Full state → docs split into received vs pending; funnel_stage derived."""
    ext = ExtractedFields(
        nombre="Juan",
        plan_credito=PlanCredito.PLAN_10,
        tipo_credito=TipoCredito.NOMINA_TARJETA,
        modelo_moto="Adventure 150 CC",
        docs_ine=True,
        docs_comprobante=True,
    )
    summary = build_handoff_summary(
        reason=HandoffReason.PAPELERIA_COMPLETA_FORM_PENDING,
        extracted=ext,
        last_inbound_text="ya los mandé",
        suggested_next_action="Visita domicilio",
        docs_per_plan=_DOCS_PER_PLAN,
    )
    assert summary.docs_recibidos == ["ine", "comprobante"]
    assert summary.docs_pendientes == ["estados_de_cuenta", "nomina"]
    # papeleria_completa is False here because two docs are pending,
    # so funnel_stage falls back to "doc" (model_moto set, papeles incompletos).
    assert summary.funnel_stage == "doc"
    assert summary.modelo_moto == "Adventure 150 CC"
    assert summary.plan_credito == "10%"
    assert summary.enganche_estimado == "10% de enganche"


def test_build_handoff_summary_empty_state_minimal_payload() -> None:
    """No tipo_credito → docs lists empty; nombre/plan are None."""
    summary = build_handoff_summary(
        reason=HandoffReason.OUTSIDE_24H_WINDOW,
        extracted=ExtractedFields(),
        last_inbound_text="hola",
        suggested_next_action="continuar",
        docs_per_plan=_DOCS_PER_PLAN,
    )
    assert summary.docs_recibidos == []
    assert summary.docs_pendientes == []
    assert summary.nombre is None
    assert summary.plan_credito is None
    assert summary.enganche_estimado is None
    assert summary.funnel_stage == "plan"


def test_build_handoff_summary_sin_comprobantes_minimal_docs() -> None:
    """Plan with the smallest doc list — only INE + comprobante required."""
    ext = ExtractedFields(
        plan_credito=PlanCredito.PLAN_20,
        tipo_credito=TipoCredito.SIN_COMPROBANTES,
        docs_ine=True,
    )
    summary = build_handoff_summary(
        reason=HandoffReason.OBSTACLE_NO_SOLUTION,
        extracted=ext,
        last_inbound_text="no tengo comprobante",
        suggested_next_action="ofrecer alternativas",
        docs_per_plan=_DOCS_PER_PLAN,
    )
    assert summary.docs_recibidos == ["ine"]
    assert summary.docs_pendientes == ["comprobante"]


def test_handoff_summary_json_serializes_reason_as_value_not_enum_repr() -> None:
    """Pydantic v2 footgun guard: the reason must round-trip as the enum
    string value ('outside_24h_window'), NOT as the repr ('HandoffReason....').

    If this ever fails, the operator dashboard's payload->>'reason' filter
    breaks and handoffs route to the wrong queue.
    """
    summary = build_handoff_summary(
        reason=HandoffReason.OUTSIDE_24H_WINDOW,
        extracted=ExtractedFields(),
        last_inbound_text="hola",
        suggested_next_action="continuar",
        docs_per_plan={},
    )
    payload = json.loads(summary.model_dump_json())
    assert payload["reason"] == "outside_24h_window"
    # And full round-trip remains a value-shaped string for every reason.
    for reason in HandoffReason:
        s = build_handoff_summary(
            reason=reason,
            extracted=ExtractedFields(),
            last_inbound_text="x",
            suggested_next_action="y",
            docs_per_plan={},
        )
        assert json.loads(s.model_dump_json())["reason"] == reason.value
