from atendia.runner.conversation_runner import (
    _render_structured_quote_messages,
    _structured_quotes_from_evidence,
)


def test_structured_quotes_from_catalog_evidence() -> None:
    chunks = [
        {
            "text": """tipo_registro: catalogo_modelo
modelo_moto: B52 250 CC
precio_contado_mxn: 64900
planes_disponibles: 10%, 15%, 20%, 30%
credito 10%: enganche_mxn 6815, pago_quincenal_mxn 2707, numero_quincenas 72
credito 20%: enganche_mxn 13629, pago_quincenal_mxn 2207, numero_quincenas 72""",
        }
    ]

    quotes = _structured_quotes_from_evidence(
        chunks=chunks,
        extracted_data={"credito_plan": "20%", "modelo_moto": "B52 250 CC"},
        inbound_text="B52",
    )

    assert quotes == [
        {
            "modelo_moto": "B52 250 CC",
            "precio_contado_mxn": "64900",
            "credito_plan": "20%",
            "enganche_mxn": "13629",
            "pago_quincenal_mxn": "2207",
            "numero_quincenas": "72",
        }
    ]


def test_render_structured_quote_single_message() -> None:
    messages = _render_structured_quote_messages(
        [
            {
                "modelo_moto": "B52 250 CC",
                "precio_contado_mxn": "64900",
                "credito_plan": "20%",
                "enganche_mxn": "13629",
                "pago_quincenal_mxn": "2207",
                "numero_quincenas": "72",
            }
        ]
    )

    assert messages == [
        "La B52 250 CC de contado queda en $64,900. Con tu plan 20%: "
        "enganche $13,629, pagos de $2,207 por 72 quincenas.\n"
        "Puedes liquidar antes sin penalizacion."
    ]
