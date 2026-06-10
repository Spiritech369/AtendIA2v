from __future__ import annotations

from atendia.agent_runtime.runtime_state_persistence import (
    _pending_confirmation_value,
    _validated_response_plan_pending_slot,
)


def test_pending_confirmation_is_truncated_to_column_limit() -> None:
    message = "x" * 220

    pending = _pending_confirmation_value(message, "income_type")

    assert pending is not None
    assert len(pending) == 160
    assert pending.endswith("...")


def test_pending_confirmation_is_empty_without_question_slot() -> None:
    assert _pending_confirmation_value("hola", None) is None


def test_validated_response_plan_pending_slot_comes_from_final_plan() -> None:
    trace = {
        "advisor_brain": {"question_slot": "employment_seniority"},
        "validated_response_plan": {
            "pending_slot": "income_type",
            "slot_consumed": False,
            "message_goal": "ask_one_clarifying_question_for_pending_slot",
        },
    }

    assert _validated_response_plan_pending_slot(trace) == "income_type"
