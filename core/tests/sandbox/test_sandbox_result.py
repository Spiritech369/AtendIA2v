from decimal import Decimal

from atendia.sandbox.result import SandboxRunResult, SandboxTurnResult


def test_turn_result_carries_composer_and_cost():
    r = SandboxTurnResult(
        flow_mode="SALES",
        nlu_output={"intent": "ASK_PRICE"},
        composer_output={"text": "El precio es..."},
        would_be_outbound=["El precio es..."],
        cost_usd=Decimal("0.0123"),
        latency_ms=812,
    )
    assert r.composer_output["text"].startswith("El precio")
    assert r.cost_usd == Decimal("0.0123")
    assert r.would_be_outbound == ["El precio es..."]


def test_total_cost_sums_turns_and_handles_empty():
    assert SandboxRunResult().total_cost_usd == Decimal("0")
    r = SandboxRunResult(
        turns=[
            SandboxTurnResult(None, None, None, [], Decimal("0.1"), None),
            SandboxTurnResult(None, None, None, [], Decimal("0.2"), None),
        ]
    )
    assert r.total_cost_usd == Decimal("0.3")
