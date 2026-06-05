from __future__ import annotations

import pytest

from atendia.simulation.advisor_first_multiturn import (
    REPORT_JSON,
    REPORT_MD,
    FAILURES_MD,
    run_simulation,
    simulation_cases,
)


def test_fixture_has_required_multiturn_cases() -> None:
    cases = simulation_cases()

    assert len(cases) == 10
    assert all(5 <= len(case.turns) <= 12 for case in cases)
    assert "Hola, donde estan y quiero la Adventure, tengo buro" in cases[0].turns[0].message
    assert any("La primera" in turn.message for turn in cases[2].turns)
    assert cases[7].turns[2].attachments
    assert any("Francisco" in turn.message for turn in cases[8].turns)


@pytest.mark.asyncio
async def test_advisor_first_multiturn_simulation_passes_and_writes_reports() -> None:
    payload = await run_simulation()

    assert payload["summary"]["cases_total"] == 10
    assert payload["summary"]["cases_failed"] == 0
    assert payload["summary"]["side_effects"] == {
        "whatsapp": 0,
        "outbox": 0,
        "database_writes": 0,
    }
    assert REPORT_MD.exists()
    assert REPORT_JSON.exists()
    assert FAILURES_MD.exists()
    assert "No failures detected" in FAILURES_MD.read_text(encoding="utf-8")

    for case in payload["cases"]:
        assert case["pass_fail"] == "pass"
        assert case["naturalidad_score"] >= 4
        assert case["repeticion_detectada"] is False
        assert case["hardcode_keyword_routing_sospechoso"] is False
        assert case["transcript"]
        for turn in case["turns"]:
            assert turn["advisor_decision"]["next_best_action"]
            assert "detected_intent" not in turn["advisor_decision"]
            assert isinstance(turn["tool_calls"], list)
            assert isinstance(turn["field_updates_applied"], list)
            assert isinstance(turn["blocked_state_updates"], list)
            assert turn["hard_validation_failures"] == []

    quoted_turns = [
        turn
        for case in payload["cases"]
        for turn in case["turns"]
        if turn["quote_snapshot_id"]
    ]
    assert quoted_turns
    assert all(turn["quote_snapshot_hash"] for turn in quoted_turns)
