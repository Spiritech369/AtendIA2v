from atendia.runner.confirmation_policy import resolve_pending_confirmation


def test_legacy_nomina_tarjeta_confirmation_resolves_yes() -> None:
    result = resolve_pending_confirmation(
        inbound_text="si",
        pending_confirmation="is_nomina_tarjeta",
        extracted_jsonb={},
    )

    assert result is not None
    assert result.answer == "yes"
    assert result.updates == {
        "tipo_credito": "NÃ³mina Tarjeta",
        "plan_credito": "10%",
    }
    assert result.extracted_data["tipo_credito"]["value"] == "NÃ³mina Tarjeta"


def test_legacy_negocio_sat_confirmation_resolves_no() -> None:
    result = resolve_pending_confirmation(
        inbound_text="nel",
        pending_confirmation="is_negocio_sat",
        extracted_jsonb={},
    )

    assert result is not None
    assert result.answer == "no"
    assert result.updates == {
        "tipo_credito": "Sin Comprobantes",
        "plan_credito": "20%",
    }
    assert result.extracted_data["plan_credito"]["value"] == "20%"


def test_legacy_confirmation_without_side_effects_stays_unresolved() -> None:
    result = resolve_pending_confirmation(
        inbound_text="si",
        pending_confirmation="is_nomina_recibos",
        extracted_jsonb={},
    )

    assert result is None
