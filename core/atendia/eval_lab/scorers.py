from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable

from atendia.agent_runtime.action_registry import ActionRegistry, default_action_registry
from atendia.agent_runtime.schemas import ActionRequest, TurnOutput
from atendia.eval_lab.schemas import EvalScenario, EvalScore

Scorer = Callable[[EvalScenario, TurnOutput], EvalScore]

QUESTION_TERMS = {
    "price": {"precio", "costo", "cuesta", "vale", "cotizacion", "cotización"},
    "appointment": {"cita", "agendar", "agenda", "horario", "mañana", "manana"},
    "human": {"humano", "asesor", "persona", "ejecutivo", "agente"},
    "hours": {"horario", "abren", "cierran", "hora"},
}

ANSWER_TERMS = {
    "price": {"precio", "costo", "cuesta", "vale", "desde", "$", "no tengo"},
    "appointment": {"cita", "agenda", "agendar", "horario", "mañana", "manana"},
    "human": {"humano", "asesor", "persona", "equipo"},
    "hours": {"horario", "abierto", "atendemos", "lunes", "martes", "sabado", "sábado"},
}


def default_scorers(registry: ActionRegistry | None = None) -> list[Scorer]:
    resolved_registry = registry or default_action_registry()
    return [
        answered_current_question,
        asked_at_most_one_question,
        did_not_emit_empty_response,
        lambda scenario, output: no_unknown_actions(
            scenario,
            output,
            registry=resolved_registry,
        ),
        field_updates_have_evidence,
        lifecycle_has_reason,
        no_multiple_final_messages,
        confidence_valid,
        no_forbidden_phrases,
        needs_human_when_low_confidence,
        expected_field_updates_present,
        expected_lifecycle_present,
        lambda scenario, output: expected_actions_present(
            scenario,
            output,
            registry=resolved_registry,
        ),
    ]


def answered_current_question(scenario: EvalScenario, output: TurnOutput) -> EvalScore:
    final_message = _normalize(output.final_message)
    if not final_message:
        return _fail("answered_current_question", "final_message is empty.")
    if output.needs_human:
        return _pass("answered_current_question", "Escalation is a valid answer.")

    input_text = _normalize(scenario.input_message)
    for intent, terms in QUESTION_TERMS.items():
        if not _contains_any(input_text, terms):
            continue
        if _contains_any(final_message, ANSWER_TERMS[intent]) or output.knowledge_citations:
            return _pass(
                "answered_current_question",
                f"Response addressed detected intent: {intent}.",
            )
        return _fail(
            "answered_current_question",
            f"Response did not address detected intent: {intent}.",
            {"intent": intent},
        )

    return _pass("answered_current_question", "No specific deterministic intent detected.")


def asked_at_most_one_question(
    scenario: EvalScenario,
    output: TurnOutput,
) -> EvalScore:
    del scenario
    question_count = output.final_message.count("?")
    if question_count <= 1:
        return _pass("asked_at_most_one_question", f"Asked {question_count} questions.")
    return _fail("asked_at_most_one_question", f"Asked {question_count} questions.")


def did_not_emit_empty_response(
    scenario: EvalScenario,
    output: TurnOutput,
) -> EvalScore:
    del scenario
    if output.needs_human or output.final_message.strip():
        return _pass("did_not_emit_empty_response")
    return _fail("did_not_emit_empty_response", "Empty final_message without needs_human.")


def no_unknown_actions(
    scenario: EvalScenario,
    output: TurnOutput,
    *,
    registry: ActionRegistry | None = None,
) -> EvalScore:
    del scenario
    resolved_registry = registry or default_action_registry()
    unknown = [
        action.name
        for action in output.actions
        if not resolved_registry.has_action(action.name)
    ]
    if not unknown:
        return _pass("no_unknown_actions")
    return _fail("no_unknown_actions", "Unknown actions emitted.", {"unknown_actions": unknown})


def field_updates_have_evidence(
    scenario: EvalScenario,
    output: TurnOutput,
) -> EvalScore:
    del scenario
    missing = [
        update.field_key
        for update in output.field_updates
        if not (update.reason or update.evidence)
    ]
    if not missing:
        return _pass("field_updates_have_evidence")
    return _fail(
        "field_updates_have_evidence",
        "Field updates missing reason/evidence.",
        {"field_keys": missing},
    )


def lifecycle_has_reason(
    scenario: EvalScenario,
    output: TurnOutput,
) -> EvalScore:
    del scenario
    update = output.lifecycle_update
    if update is None:
        return _pass("lifecycle_has_reason", "No lifecycle update emitted.")
    if update.reason and update.evidence and update.confidence is not None:
        return _pass("lifecycle_has_reason")
    return _fail("lifecycle_has_reason", "Lifecycle update lacks reason/evidence/confidence.")


def no_multiple_final_messages(
    scenario: EvalScenario,
    output: TurnOutput,
) -> EvalScore:
    del scenario
    if isinstance(output.final_message, str):
        return _pass("no_multiple_final_messages")
    return _fail("no_multiple_final_messages", "final_message is not a single string.")


def confidence_valid(
    scenario: EvalScenario,
    output: TurnOutput,
) -> EvalScore:
    del scenario
    if 0 <= float(output.confidence) <= 1:
        return _pass("confidence_valid")
    return _fail("confidence_valid", "confidence must be between 0 and 1.")


def no_forbidden_phrases(
    scenario: EvalScenario,
    output: TurnOutput,
) -> EvalScore:
    final_message = _normalize(output.final_message)
    forbidden = [
        _normalize(value.removeprefix("phrase:"))
        for value in scenario.forbidden_behaviors
    ]
    hits = [phrase for phrase in forbidden if phrase and phrase in final_message]
    if not hits:
        return _pass("no_forbidden_phrases")
    return _fail("no_forbidden_phrases", "Forbidden phrase found.", {"phrases": hits})


def needs_human_when_low_confidence(
    scenario: EvalScenario,
    output: TurnOutput,
) -> EvalScore:
    del scenario
    if output.confidence >= 0.5 or output.needs_human or output.risk_flags:
        return _pass("needs_human_when_low_confidence")
    return _fail(
        "needs_human_when_low_confidence",
        "Low confidence output must set needs_human or risk_flags.",
    )


def expected_field_updates_present(
    scenario: EvalScenario,
    output: TurnOutput,
) -> EvalScore:
    expected = set(scenario.expected_field_updates)
    actual = {update.field_key for update in output.field_updates}
    missing = sorted(expected - actual)
    if not missing:
        return _pass("expected_field_updates_present")
    return _fail(
        "expected_field_updates_present",
        "Expected field updates missing.",
        {"missing": missing},
    )


def expected_lifecycle_present(
    scenario: EvalScenario,
    output: TurnOutput,
) -> EvalScore:
    if not scenario.expected_lifecycle:
        return _pass("expected_lifecycle_present")
    target = output.lifecycle_update.target_stage if output.lifecycle_update else None
    if target == scenario.expected_lifecycle:
        return _pass("expected_lifecycle_present")
    return _fail(
        "expected_lifecycle_present",
        "Expected lifecycle target missing.",
        {"expected": scenario.expected_lifecycle, "actual": target},
    )


def expected_actions_present(
    scenario: EvalScenario,
    output: TurnOutput,
    *,
    registry: ActionRegistry | None = None,
) -> EvalScore:
    del registry
    expected = set(scenario.expected_actions)
    actual = {action.name for action in output.actions}
    missing = sorted(expected - actual)
    if not missing:
        return _pass("expected_actions_present")
    return _fail(
        "expected_actions_present",
        "Expected actions missing.",
        {"missing": missing},
    )


def _contains_any(text: str, terms: set[str]) -> bool:
    return any(term in text for term in terms)


def _normalize(value: str) -> str:
    without_accents = "".join(
        char
        for char in unicodedata.normalize("NFKD", value.casefold())
        if not unicodedata.combining(char)
    )
    return re.sub(r"\s+", " ", without_accents).strip()


def _pass(scorer: str, message: str = "", metadata: dict | None = None) -> EvalScore:
    return EvalScore(
        scorer=scorer,
        passed=True,
        score=1.0,
        message=message,
        metadata=metadata or {},
    )


def _fail(scorer: str, message: str, metadata: dict | None = None) -> EvalScore:
    return EvalScore(
        scorer=scorer,
        passed=False,
        score=0.0,
        message=message,
        metadata=metadata or {},
    )


def action_names(actions: list[ActionRequest]) -> list[str]:
    return [action.name for action in actions]
