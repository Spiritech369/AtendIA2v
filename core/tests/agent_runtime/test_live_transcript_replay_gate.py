from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from atendia.agent_runtime import live_transcript_replay_gate as gate
from atendia.agent_runtime.policy_validator import PolicyValidator
from atendia.agent_runtime.schemas import FieldUpdate, TurnOutput
from atendia.product_agents import test_lab


def test_live_transcript_replay_blocks_internal_field_not_visible() -> None:
    issues = _issue_codes("No puedo registrar ese dato porque el campo no está visible.")

    assert "internal_text_visible" in issues


def test_live_transcript_replay_writes_15_months() -> None:
    turn = _turn(3, "Perfecto, con 15 meses sí cumples. Ahora dime cómo recibes tus ingresos.")
    turn["state_writes"] = [{"field_key": "employment_seniority"}]
    turns = [_turn(1, "Hola"), _turn(2, "Claro"), turn, *_blank_turns(4, 18)]
    audit = gate.gate_audit(turns, _passed_result())

    assert "fifteen_months_not_written" not in audit["failures"]


def test_live_transcript_replay_does_not_reask_seniority_after_written() -> None:
    issues = _issue_codes("He actualizado tu antigüedad laboral a 22 años.")

    assert "generic_progress_copy" in issues


def test_live_transcript_replay_does_not_switch_to_model_when_income_missing() -> None:
    turns = [_turn(index, "ok") for index in range(1, 19)]
    turns[7]["pending_slot_after"] = "product_selection"
    audit = gate.gate_audit(turns, _passed_result())

    assert "frustration_switched_to_model_when_income_missing" in audit["failures"]


def test_business_income_requires_sat_clarification() -> None:
    turns = [_turn(index, "ok") for index in range(1, 19)]
    turns[13]["final_message"] = "La Metro queda en $1,000 de enganche."
    audit = gate.gate_audit(turns, _passed_result())

    assert "merchant_quoted_without_sat_clarification" in audit["failures"]


def test_merchant_does_not_receive_payroll_requirements() -> None:
    turns = [_turn(index, "ok") for index in range(1, 19)]
    turns[16]["final_message"] = "Ocupo INE, domicilio y recibos de nómina."
    turns[16]["pending_slot_after"] = "business_tax_status"
    audit = gate.gate_audit(turns, _passed_result())

    assert "merchant_received_payroll_requirements" in audit["failures"]


def test_price_objection_does_not_repeat_same_quote() -> None:
    turn = _turn(15, "El pago queda en $1,200 quincenal.")
    audit = gate.gate_audit(
        [*_blank_turns(1, 14), turn, *_blank_turns(16, 18)],
        _passed_result(),
    )

    assert "quote_without_quote_resolve:turn_15" in audit["failures"]


def test_robot_question_gets_honest_digital_assistant_response() -> None:
    issues = _issue_codes("Soy el asistente digital de Dinamo para ayudarte más rápido.")

    assert issues == set()


def test_customer_facing_leak_policy_blocks_internal_terms() -> None:
    for text in (
        "trace id pendiente",
        "tool requirements.lookup falló",
        "pending_slot income_type",
        "runtime error técnico",
    ):
        assert "internal_text_visible" in _issue_codes(text)


def test_no_live_until_transcript_replay_passes() -> None:
    env = Path(__file__).resolve().parents[2] / ".env"
    content = env.read_text(encoding="utf-8")

    assert "ATENDIA_V2_AGENT_RUNTIME_V2_SEND_ENABLED=false" in content


def test_real_mode_limits_allow_only_marked_live_transcript_incident_replay() -> None:
    scenario = SimpleNamespace(
        turns=[{"inbound_text": "x"} for _ in range(18)],
        metadata_json={"live_transcript_replay_gate": True},
    )
    suite = SimpleNamespace(
        mode="incident_replay",
        metadata_json={"live_transcript_replay_gate": True},
    )

    assert (
        test_lab._real_mode_limits_blocker(
            execution_mode=test_lab.RUNTIME_V2_AGENT_SERVICE_MODE,
            suite=suite,
            scenarios=[scenario],
        )
        is None
    )


def test_real_mode_limits_still_block_unmarked_long_scenarios() -> None:
    scenario = SimpleNamespace(turns=[{"inbound_text": "x"} for _ in range(18)], metadata_json={})
    suite = SimpleNamespace(mode="incident_replay", metadata_json={})

    assert test_lab._real_mode_limits_blocker(
        execution_mode=test_lab.RUNTIME_V2_AGENT_SERVICE_MODE,
        suite=suite,
        scenarios=[scenario],
    ) == "real_mode_max_turns_exceeded"


def _issue_codes(message: str) -> set[str]:
    output = TurnOutput(
        final_message=message,
        confidence=0.8,
        needs_human=False,
        field_updates=[
            FieldUpdate(
                field_key="evidence_probe",
                value=True,
                reason="test evidence",
                evidence=["test"],
                confidence=1.0,
            )
        ],
    )
    return {issue.code for issue in PolicyValidator().validate(output)}


def _turn(number: int, final_message: str) -> dict[str, Any]:
    return {
        "turn_number": number,
        "final_message": final_message,
        "send_decision": "no_send",
        "tool_results": [],
        "state_writes": [],
        "pending_slot_after": "",
    }


def _blank_turns(start: int, end: int) -> list[dict[str, Any]]:
    return [_turn(index, "ok") for index in range(start, end + 1)]


def _passed_result() -> dict[str, Any]:
    return {
        "run_status": "passed",
        "db_audit_after": {
            "outbound_outbox_pending_retry": 0,
            "business_event_ledger_side_effects_allowed": 0,
        },
    }
