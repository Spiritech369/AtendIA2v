from __future__ import annotations

import re
from dataclasses import dataclass

from atendia.agent_runtime.respond_style_turn_contract import (
    AgentContextPackage,
    AgentTurnRetryInstruction,
    AgentTurnValidationResult,
    FinalTurnDecision,
    LLMAgentTurnOutput,
    LLMClaim,
    ValidationErrorItem,
)

_INTERNAL_LEAK_RE = re.compile(
    r"\b(json|trace|tool|prompt|workflow|outbox|statewriter|state writer)\b",
    re.IGNORECASE,
)
_PRICE_RE = re.compile(
    r"(?:\$|(?:\b\d{2,}(?:[,.]\d{3})*(?:\.\d+)?\s*(?:mxn|pesos?)\b))",
    re.IGNORECASE,
)
_REQUIREMENTS_RE = re.compile(
    r"\b(requirements?|documentos?|papeles?|ine|comprobante|recibos?)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class RespondStyleTurnValidatorConfig:
    max_retry_attempts: int = 2
    quote_tool_name: str = "quote.resolve"
    requirements_tool_names: tuple[str, ...] = (
        "requirements.lookup",
        "requirements.resolve",
        "lookup_requirements",
    )


class RespondStyleTurnValidator:
    """Deterministic validator for LLM-authored Product-First turn proposals.

    The validator does not call providers, execute tools, write state, enqueue
    outbound messages, or run workflows. It only classifies a proposed turn.
    """

    def __init__(self, config: RespondStyleTurnValidatorConfig | None = None) -> None:
        self._config = config or RespondStyleTurnValidatorConfig()

    def validate(
        self,
        *,
        output: LLMAgentTurnOutput,
        context: AgentContextPackage,
        attempt_number: int = 1,
    ) -> FinalTurnDecision:
        errors = self._validate_output(output=output, context=context)
        retryable = [item for item in errors if item.retryable]
        blocked = [item for item in errors if not item.retryable]

        if not errors:
            validation = AgentTurnValidationResult(
                status="valid",
                accepted_tool_requests=list(output.tool_requests),
                accepted_field_writes=list(output.field_write_proposals),
                accepted_actions=list(output.action_proposals),
                accepted_workflow_events=list(output.workflow_event_proposals),
                send_decision="send",
            )
            return FinalTurnDecision(
                final_message=output.final_message,
                send_decision="send",
                validation=validation,
                accepted_field_writes=list(output.field_write_proposals),
                accepted_actions=list(output.action_proposals),
                accepted_workflow_events=list(output.workflow_event_proposals),
                trace_metadata={"respond_style_validator": {"status": "valid"}},
            )

        if retryable and not blocked and attempt_number < self._config.max_retry_attempts:
            validation = AgentTurnValidationResult(
                status="invalid_retryable",
                retryable=True,
                feedback_for_llm=_feedback_for_llm(retryable),
                blocked_items=retryable,
                send_decision="no_send",
            )
            retry = AgentTurnRetryInstruction(
                attempt_number=attempt_number,
                max_attempts=self._config.max_retry_attempts,
                feedback_for_llm=validation.feedback_for_llm or "",
                error_items=retryable,
            )
            return FinalTurnDecision(
                final_message=None,
                send_decision="no_send",
                validation=validation,
                retry_instruction=retry,
                trace_metadata={"respond_style_validator": {"status": "retry"}},
            )

        blocked_reason = _blocked_reason(errors)
        validation = AgentTurnValidationResult(
            status="blocked",
            blocked_items=errors,
            send_decision="no_send",
            blocked_reason=blocked_reason,
        )
        return FinalTurnDecision(
            final_message=None,
            send_decision="no_send",
            validation=validation,
            trace_metadata={"respond_style_validator": {"status": "blocked"}},
        )

    def _validate_output(
        self,
        *,
        output: LLMAgentTurnOutput,
        context: AgentContextPackage,
    ) -> list[ValidationErrorItem]:
        errors: list[ValidationErrorItem] = []
        text = output.final_message.strip()

        if not text:
            errors.append(_error("final_message_empty", "final_message is required"))

        if _INTERNAL_LEAK_RE.search(text):
            errors.append(
                _error(
                    "internal_text_visible",
                    "final_message contains internal operational text",
                    path="final_message",
                )
            )

        errors.extend(_claim_errors(output.claims, context))

        if _contains_price(output) and not _tool_succeeded(
            context,
            self._config.quote_tool_name,
        ):
            errors.append(
                _error(
                    "missing_quote_tool",
                    "price claims require quote.resolve tool result",
                    path="final_message",
                )
            )

        if _contains_requirements(output) and not any(
            _tool_succeeded(context, tool_name)
            for tool_name in self._config.requirements_tool_names
        ):
            errors.append(
                _error(
                    "missing_requirements_tool",
                    "requirements claims require requirements tool result",
                    path="final_message",
                )
            )

        errors.extend(_field_write_errors(output, context))
        errors.extend(_workflow_errors(output, context))
        errors.extend(_action_errors(output, context))
        errors.extend(_handoff_errors(output, context))
        return errors


def _error(code: str, message: str, *, path: str | None = None) -> ValidationErrorItem:
    return ValidationErrorItem(code=code, message=message, path=path, retryable=True)


def _feedback_for_llm(errors: list[ValidationErrorItem]) -> str:
    return "Fix validation errors before sending: " + "; ".join(
        f"{item.code}: {item.message}" for item in errors
    )


def _blocked_reason(errors: list[ValidationErrorItem]) -> str:
    return ",".join(item.code for item in errors) or "respond_style_validation_blocked"


def _claim_errors(
    claims: list[LLMClaim],
    context: AgentContextPackage,
) -> list[ValidationErrorItem]:
    errors: list[ValidationErrorItem] = []
    available_refs = _available_source_refs(context)
    for index, claim in enumerate(claims):
        if claim.basis in {"tool_result", "knowledge_source", "agent_policy"}:
            if not claim.source_refs:
                errors.append(
                    _error(
                        "claim_missing_source_ref",
                        "claim requires source_refs",
                        path=f"claims[{index}].source_refs",
                    )
                )
                continue
            missing = [ref for ref in claim.source_refs if ref not in available_refs]
            if missing:
                errors.append(
                    _error(
                        "claim_source_ref_not_available",
                        "claim source_refs are not present in context",
                        path=f"claims[{index}].source_refs",
                    )
                )
    return errors


def _available_source_refs(context: AgentContextPackage) -> set[str]:
    refs: set[str] = set()
    for item in context.tool_results:
        refs.update(_ids_from_item(item, keys=("tool_name", "name", "tool_id", "id")))
    for item in context.retrieved_context:
        refs.update(_ids_from_item(item, keys=("source_id", "id", "title")))
    for item in context.knowledge_bindings:
        refs.update(_ids_from_item(item, keys=("source_id", "id", "name")))
    policy_id = context.send_policy.get("policy_id") or context.agent_identity.get("policy_id")
    if policy_id:
        refs.add(str(policy_id))
    return refs


def _ids_from_item(item: object, *, keys: tuple[str, ...]) -> set[str]:
    if not isinstance(item, dict):
        return set()
    values: set[str] = set()
    for key in keys:
        value = item.get(key)
        if value is not None:
            values.add(str(value))
    return values


def _contains_price(output: LLMAgentTurnOutput) -> bool:
    return bool(
        _PRICE_RE.search(output.final_message)
        or any(_PRICE_RE.search(claim.text) for claim in output.claims)
    )


def _contains_requirements(output: LLMAgentTurnOutput) -> bool:
    return bool(
        _REQUIREMENTS_RE.search(output.final_message)
        or any(_REQUIREMENTS_RE.search(claim.text) for claim in output.claims)
    )


def _tool_succeeded(context: AgentContextPackage, tool_name: str) -> bool:
    for item in context.tool_results:
        if not isinstance(item, dict):
            continue
        name = item.get("tool_name") or item.get("name") or item.get("tool_id")
        status = item.get("status")
        if name == tool_name and status == "succeeded":
            return True
    return False


def _field_write_errors(
    output: LLMAgentTurnOutput,
    context: AgentContextPackage,
) -> list[ValidationErrorItem]:
    allowed_fields = {
        str(item.get("field_key") or item.get("key"))
        for item in context.field_policies
        if isinstance(item, dict) and item.get("writable", True) is not False
    }
    errors: list[ValidationErrorItem] = []
    for index, proposal in enumerate(output.field_write_proposals):
        if proposal.field_key not in allowed_fields:
            errors.append(
                _error(
                    "field_policy_missing",
                    "field write requires writable field policy",
                    path=f"field_write_proposals[{index}].field_key",
                )
            )
        if not proposal.evidence:
            errors.append(
                _error(
                    "field_write_without_evidence",
                    "field write requires evidence",
                    path=f"field_write_proposals[{index}].evidence",
                )
            )
    return errors


def _workflow_errors(
    output: LLMAgentTurnOutput,
    context: AgentContextPackage,
) -> list[ValidationErrorItem]:
    allowed_bindings = {
        str(item.get("binding_name") or item.get("name"))
        for item in context.workflow_trigger_schemas
        if isinstance(item, dict) and item.get("enabled", True) is not False
    }
    errors: list[ValidationErrorItem] = []
    for index, proposal in enumerate(output.workflow_event_proposals):
        if proposal.binding_name not in allowed_bindings:
            errors.append(
                _error(
                    "workflow_binding_missing",
                    "workflow event requires enabled binding",
                    path=f"workflow_event_proposals[{index}].binding_name",
                )
            )
    return errors


def _action_errors(
    output: LLMAgentTurnOutput,
    context: AgentContextPackage,
) -> list[ValidationErrorItem]:
    allowed_actions = {
        str(item.get("action_name") or item.get("name") or item.get("key"))
        for item in context.action_schemas
        if isinstance(item, dict)
        and item.get("enabled", True) is not False
        and item.get("permitted", True) is not False
    }
    errors: list[ValidationErrorItem] = []
    for index, proposal in enumerate(output.action_proposals):
        if proposal.action_name not in allowed_actions:
            errors.append(
                _error(
                    "action_not_allowed",
                    "action requires enabled permitted schema",
                    path=f"action_proposals[{index}].action_name",
                )
            )
    return errors


def _handoff_errors(
    output: LLMAgentTurnOutput,
    context: AgentContextPackage,
) -> list[ValidationErrorItem]:
    proposal = output.handoff_proposal
    if proposal is None or not proposal.needed:
        return []
    if context.handoff_policy.get("enabled") is False:
        return [
            _error(
                "handoff_not_allowed",
                "handoff proposal requires enabled handoff policy",
                path="handoff_proposal",
            )
        ]
    allowed_targets = context.handoff_policy.get("targets") or []
    if allowed_targets and proposal.target not in allowed_targets:
        return [
            _error(
                "handoff_target_not_allowed",
                "handoff target is not allowed by policy",
                path="handoff_proposal.target",
            )
        ]
    return []


__all__ = [
    "RespondStyleTurnValidator",
    "RespondStyleTurnValidatorConfig",
]

