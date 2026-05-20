from types import SimpleNamespace

from atendia.contracts.flow_mode import FlowMode
from atendia.runner.runner_layers import build_runner_layers


def test_runner_layers_explain_quote_stage_in_human_language() -> None:
    pipeline = SimpleNamespace(
        stages=[
            SimpleNamespace(id="datos", label="Datos"),
            SimpleNamespace(id="cotizacion", label="cotización"),
        ],
        documents_catalog=[],
        docs_per_plan={},
    )
    layers = build_runner_layers(
        pipeline=pipeline,
        previous_stage="datos",
        next_stage="cotizacion",
        decision_action="quote",
        decision_reason="transition:datos->cotizacion",
        flow_mode=FlowMode.SALES,
        action_payload={"status": "ok", "name": "TC250"},
        extracted_data={
            "tiempo_empleo_meses": {"value": 8},
            "tipo_credito": {"value": "Sin Comprobantes"},
            "modelo_interes": {"value": "TC250"},
        },
        rules_evaluated=[],
        router_trigger="sales_quote:keyword_in_text",
        pause_bot=False,
    )

    assert set(layers) == {"data", "decision", "payload", "explanation"}
    assert layers["decision"]["stage_moved"] is True
    assert layers["payload"]["keys"] == ["name", "status"]
    assert (
        layers["explanation"]["summary"]
        == 'El cliente fue movido a "cotización" porque ya tiene antigüedad válida, '
        "tipo_credito asignado, modelo_interes detectado."
    )
