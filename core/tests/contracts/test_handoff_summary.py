"""HandoffSummary persisted in human_handoffs.payload JSONB.

Frontend (Phase 4) and human agents read this to understand context
before responding. Six reasons covering all v1 escalation triggers.
"""
from atendia.contracts.handoff_summary import HandoffReason, HandoffSummary


def test_handoff_reasons_match_v1_triggers() -> None:
    """Los 6 motivos del v1 prompt + outside_24h + composer_failed."""
    expected = {
        "outside_24h_window",
        "composer_failed",
        "obstacle_no_solution",
        "user_signaled_papeleria_completa",
        "papeleria_completa_form_pending",
        "antiguedad_lt_6m",
    }
    actual = {r.value for r in HandoffReason}
    assert expected == actual


def test_handoff_summary_minimal() -> None:
    """Solo reason y last_inbound_message son requeridos."""
    h = HandoffSummary(
        reason=HandoffReason.ANTIGUEDAD_LT_6M,
        last_inbound_message="tengo 3 meses",
        suggested_next_action="Esperar a que cumpla 6 meses",
        funnel_stage="plan",
        docs_recibidos=[],
        docs_pendientes=[],
    )
    assert h.reason == HandoffReason.ANTIGUEDAD_LT_6M


def test_handoff_summary_round_trip_json() -> None:
    """JSONB serialization safe."""
    h = HandoffSummary(
        reason=HandoffReason.PAPELERIA_COMPLETA_FORM_PENDING,
        nombre="Juan",
        modelo_moto="Adventure 150 CC",
        plan_credito="10%",
        enganche_estimado="$3,140",
        docs_recibidos=["ine", "comprobante", "estados_de_cuenta", "nomina"],
        docs_pendientes=[],
        last_inbound_message="ya los mandé todos",
        suggested_next_action="Visita domicilio/trabajo",
        funnel_stage="close",
    )
    raw = h.model_dump(mode="json")
    rebuilt = HandoffSummary.model_validate(raw)
    assert rebuilt.reason == HandoffReason.PAPELERIA_COMPLETA_FORM_PENDING
    assert rebuilt.docs_recibidos == ["ine", "comprobante", "estados_de_cuenta", "nomina"]
