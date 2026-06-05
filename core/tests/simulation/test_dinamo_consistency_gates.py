from __future__ import annotations

from atendia.simulation.dinamo_consistency_gates import (
    CopyStateConsistencyValidator,
    QuoteConsistencyValidator,
    UiConsistencyValidator,
    render_quote_message,
)


def test_r4_final_message_and_r4_snapshot_passes() -> None:
    result = QuoteConsistencyValidator().validate(
        final_message="La R4 250 CC de contado queda en $52,700.",
        fields={
            "Moto": "R4",
            "Plan_Credito": "Contado",
            "Plan_Enganche": "100%",
            "Cotizacion_Enviada": True,
            "Ultima_Cotizacion": {
                "status": "ok",
                "moto": "R4 250 CC",
                "plan_credito": "Contado",
                "plan_enganche": "100%",
                "precio_contado_mxn": 52700,
                "citation": {"content_type": "catalog"},
            },
        },
    )

    assert result.passed


def test_r4_final_message_and_adventure_snapshot_fails() -> None:
    result = QuoteConsistencyValidator().validate(
        final_message="La R4 250 CC de contado queda en $52,700.",
        fields={
            "Moto": "R4",
            "Plan_Credito": "Contado",
            "Plan_Enganche": "100%",
            "Cotizacion_Enviada": True,
            "Ultima_Cotizacion": {
                "status": "ok",
                "moto": "Adventure Elite 150 CC",
                "plan_credito": "Contado",
                "plan_enganche": "100%",
                "precio_contado_mxn": 52700,
                "citation": {"content_type": "catalog"},
            },
        },
    )

    assert not result.passed
    assert "quote_moto_field_mismatch" in result.issues
    assert "quote_final_message_moto_mismatch" in result.issues


def test_price_mismatch_fails() -> None:
    result = QuoteConsistencyValidator().validate(
        final_message="La R4 250 CC de contado queda en $52,700.",
        fields={
            "Moto": "R4 250 CC",
            "Plan_Credito": "Contado",
            "Plan_Enganche": "100%",
            "Cotizacion_Enviada": True,
            "Ultima_Cotizacion": {
                "status": "ok",
                "moto": "R4 250 CC",
                "plan_credito": "Contado",
                "plan_enganche": "100%",
                "precio_contado_mxn": 29900,
                "citation": {"content_type": "catalog"},
            },
        },
    )

    assert not result.passed
    assert "quote_price_mismatch" in result.issues


def test_credit_quote_with_null_plan_fails() -> None:
    result = QuoteConsistencyValidator().validate(
        final_message="La Comando con Nomina Tarjeta queda en enganche $8,390.",
        fields={
            "Moto": "Comando 400 CC",
            "Plan_Credito": "Nomina Tarjeta",
            "Plan_Enganche": "10%",
            "Cotizacion_Enviada": True,
            "Ultima_Cotizacion": {
                "status": "ok",
                "moto": "Comando 400 CC",
                "plan_credito": None,
                "plan_enganche": "10%",
                "enganche_mxn": 8390,
                "citation": {"content_type": "catalog"},
            },
        },
    )

    assert not result.passed
    assert "quote_credit_plan_missing" in result.issues


def test_credit_quote_with_null_enganche_fails() -> None:
    result = QuoteConsistencyValidator().validate(
        final_message="La Comando con Nomina Tarjeta queda en pagos de $3,333.",
        fields={
            "Moto": "Comando 400 CC",
            "Plan_Credito": "Nomina Tarjeta",
            "Plan_Enganche": "10%",
            "Cotizacion_Enviada": True,
            "Ultima_Cotizacion": {
                "status": "ok",
                "moto": "Comando 400 CC",
                "plan_credito": "Nomina Tarjeta",
                "plan_enganche": None,
                "pago_quincenal_mxn": 3333,
                "citation": {"content_type": "catalog"},
            },
        },
    )

    assert not result.passed
    assert "quote_credit_enganche_missing" in result.issues


def test_contado_asking_credit_docs_fails() -> None:
    result = QuoteConsistencyValidator().validate(
        final_message="La R4 de contado queda en $52,700. Para avanzar el credito manda tu INE.",
        fields={
            "Moto": "R4 250 CC",
            "Plan_Credito": "Contado",
            "Plan_Enganche": "100%",
            "Cotizacion_Enviada": True,
            "Ultima_Cotizacion": {
                "status": "ok",
                "moto": "R4 250 CC",
                "plan_credito": "Contado",
                "plan_enganche": "100%",
                "precio_contado_mxn": 52700,
                "citation": {"content_type": "catalog"},
            },
        },
    )

    assert not result.passed
    assert "quote_contado_asks_credit_docs" in result.issues


def test_valid_contado_quote_passes() -> None:
    message = render_quote_message(
        {
            "moto": "R4 250 CC",
            "plan_credito": "Contado",
            "precio_contado_mxn": 52700,
        }
    )
    result = QuoteConsistencyValidator().validate(
        final_message=message,
        fields={
            "Moto": "R4 250 CC",
            "Plan_Credito": "Contado",
            "Plan_Enganche": "100%",
            "Cotizacion_Enviada": True,
            "Ultima_Cotizacion": {
                "status": "ok",
                "moto": "R4 250 CC",
                "plan_credito": "Contado",
                "plan_enganche": "100%",
                "precio_contado_mxn": 52700,
                "citation": {"content_type": "catalog"},
            },
        },
    )

    assert result.passed
    assert "asesor" in message
    assert "INE" not in message


def test_state_nomina_tarjeta_and_copy_nomina_recibos_fails() -> None:
    result = CopyStateConsistencyValidator().validate(
        final_message="Con Nomina Recibos te toca 15% de enganche.",
        fields={"Plan_Credito": "Nomina Tarjeta", "Plan_Enganche": "10%"},
    )

    assert not result.passed
    assert "copy_plan_state_mismatch" in result.issues
    assert "copy_enganche_state_mismatch" in result.issues


def test_contado_copy_pide_ine_fails() -> None:
    result = CopyStateConsistencyValidator().validate(
        final_message="Para avanzar tu credito manda INE y comprobante.",
        fields={"Plan_Credito": "Contado", "Plan_Enganche": "100%"},
    )

    assert not result.passed
    assert "copy_contado_asks_credit_docs" in result.issues


def test_copy_document_received_without_attachment_fails() -> None:
    result = CopyStateConsistencyValidator().validate(
        final_message="Ya tengo tus documentos recibidos.",
        fields={"Plan_Credito": "Nomina Tarjeta", "Plan_Enganche": "10%"},
        attachments=[],
    )

    assert not result.passed
    assert "copy_claims_docs_without_attachment" in result.issues


def test_ui_grouping_flags_debug_and_structured_fields() -> None:
    result = UiConsistencyValidator().validate_fields(
        [
            {
                "key": "simulation_run_id",
                "group": "debug",
                "render_mode": "text",
                "is_debug": True,
            },
            {
                "key": "Ultima_Cotizacion",
                "group": "tecnicos",
                "render_mode": "quote_card",
                "render_payload": {"status": "ok"},
            },
            {
                "key": "Docs_Checklist",
                "group": "tecnicos",
                "render_mode": "document_checklist",
                "render_payload": [],
            },
        ]
    )

    assert result.passed
