from __future__ import annotations

from atendia.agent_runtime.policy_validator import PolicyValidator
from atendia.agent_runtime.schemas import FieldUpdate, TurnOutput


def _codes(output: TurnOutput) -> set[str]:
    return {issue.code for issue in PolicyValidator().validate(output)}


def test_policy_flags_field_update_without_evidence() -> None:
    codes = _codes(
        TurnOutput(
            final_message="Claro, te ayudo.",
            confidence=0.8,
            field_updates=[
                FieldUpdate(
                    field_key="budget",
                    value="5000",
                    reason=None,
                    evidence=[],
                    confidence=0.8,
                    source="ai_inference",
                )
            ],
        )
    )

    assert "field_update_missing_evidence" in codes


def test_policy_flags_field_update_without_confidence() -> None:
    codes = _codes(
        TurnOutput(
            final_message="Claro, te ayudo.",
            confidence=0.8,
            field_updates=[
                FieldUpdate(
                    field_key="budget",
                    value="5000",
                    reason="Customer stated budget.",
                    evidence=["Tengo 5000"],
                    confidence=None,
                    source="customer_message",
                )
            ],
        )
    )

    assert "field_update_missing_confidence" in codes


def test_policy_flags_placeholder_final_message() -> None:
    codes = _codes(TurnOutput(final_message="Enganche $X, pagos de $Y.", confidence=0.8))

    assert "final_message_placeholder" in codes


def test_policy_flags_approval_promise() -> None:
    codes = _codes(TurnOutput(final_message="Seguro te aprueban el credito.", confidence=0.8))

    assert "approval_promise" in codes
