from atendia.contracts.flow_mode import FlowMode
from atendia.contracts.tone import Tone
from atendia.runner.composer_protocol import ComposerInput, ComposerOutput
from atendia.runner.composer_validator import validate_composer_output


def _input(**kwargs):
    data = {
        "action": "quote",
        "current_stage": "quote",
        "tone": Tone(),
        "flow_mode": FlowMode.SALES,
        "action_payload": {
            "status": "ok",
            "name": "Dinamo U5",
            "price_contado_mxn": 32900,
            "enganche": 3290,
            "pago_quincenal": 950,
        },
    }
    data.update(kwargs)
    return ComposerInput(**data)


def test_validator_passes_verified_sales_quote():
    result = validate_composer_output(
        input=_input(),
        output=ComposerOutput(
            messages=[
                "La Dinamo U5 está en $32,900 de contado. "
                "Con enganche de $3,290 te queda en pago quincenal de $950. "
                "¿Avanzamos con documentos?"
            ]
        ),
    )

    assert result.policy_passed is True
    assert result.used_action_payload is True
    assert result.invented_data is False
    assert result.followed_mode is True


def test_validator_blocks_invented_price():
    result = validate_composer_output(
        input=_input(),
        output=ComposerOutput(messages=["La Dinamo U5 está en $35,900. ¿Te la aparto?"]),
    )

    assert result.policy_passed is False
    assert result.invented_data is True
    assert any(issue.code == "invented_price" for issue in result.issues)


def test_validator_blocks_approval_promise():
    result = validate_composer_output(
        input=_input(),
        output=ComposerOutput(messages=["Te aprobamos el crédito al 100%. ¿Me mandas tus datos?"]),
    )

    assert result.policy_passed is False
    assert result.needs_handoff is True
    assert any(issue.code == "approval_promise" for issue in result.issues)


def test_validator_allows_sales_no_data_model_question():
    result = validate_composer_output(
        input=_input(action_payload={"status": "no_data", "missing": ["modelo_interes"]}),
        output=ComposerOutput(messages=["¿Qué modelo exacto de moto te interesa cotizar?"]),
    )

    assert result.policy_passed is True
    assert result.followed_mode is True
    assert result.used_action_payload is True
