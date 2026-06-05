from __future__ import annotations

from pathlib import Path

import yaml

from atendia.agent_runtime.schemas import TurnOutput
from atendia.simulation.run_dinamo_frontend_review import (
    _replace_placeholder_quote,
    _turn_payload,
)


def test_dinamo_frontend_review_v2_fixture_has_12_realistic_cases() -> None:
    path = Path("atendia/simulation/fixtures/dinamo_frontend_review_v2.yaml")
    fixture = yaml.safe_load(path.read_text(encoding="utf-8"))

    assert len(fixture["cases"]) >= 12
    assert all(5 <= len(case["turns"]) <= 12 for case in fixture["cases"])
    assert any(
        turn.get("attachment") or turn.get("attachments")
        for case in fixture["cases"]
        for turn in case["turns"]
    )


def test_quote_placeholder_is_replaced_with_quote_resolver_snapshot() -> None:
    output = TurnOutput(
        final_message=(
            "La Adventure de contado queda en $XX,XXX. Enganche $X,XXX, "
            "pagos de $X,XXX por X quincenas."
        )
    )

    replaced = _replace_placeholder_quote(
        output,
        {
            "moto": "Adventure Elite 150 CC",
            "plan_credito": "Nomina Tarjeta",
            "precio_contado_mxn": 29900,
            "enganche_mxn": 3140,
            "pago_quincenal_mxn": 1247,
            "numero_quincenas": 72,
        },
    )

    assert "$X" not in replaced.final_message
    assert "$29,900" in replaced.final_message
    assert "$3,140" in replaced.final_message
    assert "72 quincenas" in replaced.final_message


def test_frontend_turn_payload_hard_fails_on_placeholder() -> None:
    payload = _turn_payload(
        case_id="case",
        turn_index=1,
        customer_message="Cotizamela",
        attachments=[],
        output=TurnOutput(final_message="Enganche $X, pagos de $Y."),
        policy_issues=[],
        field_applied=0,
        stage_applied=None,
        fields_after={},
        stage_after="plan",
        trace_id=__import__("uuid").uuid4(),
    )

    assert payload["pass_fail"] == "fail"
    assert "placeholder_leak" in payload["failure_reasons"]
