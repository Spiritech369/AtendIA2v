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

# Safety tripwire only. Hard fact gating belongs to declarative hard
# policies (tenant-provided via AgentContextPackage.hard_policies, or the
# built-in defaults below). Regex is never the brain.
_INTERNAL_LEAK_RE = re.compile(
    r"\b(json|trace|tool|prompt|workflow|outbox|statewriter|state writer)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class HardPolicy:
    """Declarative fact-support policy.

    ``trigger_patterns``: regexes; if any matches visible copy or claim
    text, the policy applies.
    ``requires_any``: the policy is met when at least one requirement
    holds. Supported requirement forms:
    - ``tool:<tool_name>``: that tool has a succeeded tool_result in context.
    - ``basis:<claim_basis>``: the output declares at least one claim with
      that basis whose source_refs are all available in context.
    """

    policy_id: str
    description: str
    trigger_patterns: tuple[str, ...]
    requires_any: tuple[str, ...]
    error_code: str | None = None


@dataclass(frozen=True)
class RespondStyleTurnValidatorConfig:
    max_retry_attempts: int = 2
    quote_tool_name: str = "quote.resolve"
    requirements_tool_names: tuple[str, ...] = (
        "requirements.lookup",
        "requirements.resolve",
        "lookup_requirements",
    )


def default_hard_policies(config: RespondStyleTurnValidatorConfig) -> tuple[HardPolicy, ...]:
    """Built-in bilingual safety defaults, used only when the tenant
    supplies no hard_policies in the context package."""
    return (
        HardPolicy(
            policy_id="default_price_support",
            description="price mentions require a quote tool result or a cited knowledge source",
            trigger_patterns=(
                r"\$\s*\d",
                r"\b\d[\d,.]*\s*(?:mil\s+)?(?:mxn|pesos?)\b",
                r"\b(?:precio|cuesta|costo|cotizaci[oó]n|price|cost)\b[^.?!]*\d",
            ),
            requires_any=(
                f"tool:{config.quote_tool_name}",
                "basis:knowledge_source",
            ),
            error_code="missing_quote_tool",
        ),
        HardPolicy(
            policy_id="default_requirements_support",
            description=(
                "requirement listings require a requirements tool result "
                "or a cited knowledge source"
            ),
            trigger_patterns=(
                r"\b(?:requisitos?|requirements?)\b",
                r"\b(?:documentos?|papeles?)\b[^.?!]*\b(?:necesitas?|ocupas?|requieres?|"
                r"necesarios?|requeridos?|pedimos|need|required)\b",
                r"\b(?:necesitas?|ocupas?|need|required)\b[^.?!]*\b(?:documentos?|papeles?)\b",
            ),
            requires_any=(
                *(f"tool:{name}" for name in config.requirements_tool_names),
                "basis:knowledge_source",
            ),
            error_code="missing_requirements_tool",
        ),
    )


class RespondStyleTurnValidator:
    """Deterministic validator for LLM-authored Product-First turn proposals.

    The validator does not call providers, execute tools, write state, enqueue
    outbound messages, or run workflows. It only classifies a proposed turn.

    Fact-support gates apply only to visible customer copy
    (``final_response`` and the optional ``handoff_request`` message).
    ``tool_request`` turns carry no customer copy by contract, so they are
    never fact-gated: proposing a tool about a topic is not a claim.
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
            send_decision = "send" if output.turn_kind == "final_response" else "no_send"
            validation = AgentTurnValidationResult(
                status="valid",
                accepted_tool_requests=list(output.tool_requests),
                accepted_field_writes=list(output.field_write_proposals),
                accepted_actions=list(output.action_proposals),
                accepted_workflow_events=list(output.workflow_event_proposals),
                send_decision=send_decision,
            )
            accepted_handoff = (
                output.handoff_proposal
                if output.handoff_proposal is not None and output.handoff_proposal.needed
                else None
            )
            return FinalTurnDecision(
                final_message=output.final_message,
                send_decision=send_decision,
                validation=validation,
                accepted_field_writes=list(output.field_write_proposals),
                accepted_actions=list(output.action_proposals),
                accepted_workflow_events=list(output.workflow_event_proposals),
                accepted_handoff=accepted_handoff,
                trace_metadata={
                    "respond_style_validator": {
                        "status": "valid",
                        "turn_kind": output.turn_kind,
                    }
                },
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
        text = (output.final_message or "").strip()

        if output.turn_kind == "final_response" and not text:
            errors.append(_error("final_message_empty", "final_message is required"))

        if output.turn_kind == "tool_request":
            if text:
                errors.append(
                    _error(
                        "tool_request_has_customer_copy",
                        "tool_request turns must not contain customer copy",
                        path="final_message",
                    )
                )
            if not output.tool_requests:
                errors.append(
                    _error(
                        "tool_request_without_tools",
                        "tool_request turns require at least one tool request",
                        path="tool_requests",
                    )
                )
            errors.extend(_tool_binding_errors(output, context))

        if output.turn_kind == "handoff_request" and (
            output.handoff_proposal is None or not output.handoff_proposal.needed
        ):
            errors.append(
                _error(
                    "handoff_request_without_proposal",
                    "handoff_request turns require a needed handoff proposal",
                    path="handoff_proposal",
                )
            )

        # Fact gates apply only to visible customer copy.
        if text and output.turn_kind != "tool_request":
            if _INTERNAL_LEAK_RE.search(text):
                errors.append(
                    _error(
                        "internal_text_visible",
                        "final_message contains internal operational text",
                        path="final_message",
                    )
                )
            errors.extend(_claim_errors(output.claims, context))
            errors.extend(self._hard_policy_errors(output, context))

        errors.extend(_field_write_errors(output, context))
        errors.extend(_workflow_errors(output, context))
        errors.extend(_action_errors(output, context))
        errors.extend(_handoff_errors(output, context))
        return errors

    def _hard_policy_errors(
        self,
        output: LLMAgentTurnOutput,
        context: AgentContextPackage,
    ) -> list[ValidationErrorItem]:
        policies, parse_errors = _resolve_hard_policies(context, self._config)
        errors: list[ValidationErrorItem] = list(parse_errors)
        visible_texts = [output.final_message or ""] + [claim.text for claim in output.claims]
        for policy in policies:
            if not _policy_triggered(policy, visible_texts):
                continue
            if _policy_supported(policy, output, context):
                continue
            errors.append(
                _error(
                    policy.error_code or f"hard_policy_unsupported:{policy.policy_id}",
                    f"hard policy '{policy.policy_id}' requires fact support: "
                    f"{policy.description}",
                    path="final_message",
                )
            )
        return errors


def _resolve_hard_policies(
    context: AgentContextPackage,
    config: RespondStyleTurnValidatorConfig,
) -> tuple[list[HardPolicy], list[ValidationErrorItem]]:
    """Tenant hard_policies replace the built-in defaults entirely.

    A malformed tenant policy is a non-retryable blocker: a broken safety
    config must surface in Test Lab, never run silently unguarded.
    """
    raw_policies = context.hard_policies
    if not raw_policies:
        return list(default_hard_policies(config)), []
    policies: list[HardPolicy] = []
    errors: list[ValidationErrorItem] = []
    for index, item in enumerate(raw_policies):
        parsed = _parse_hard_policy(item)
        if parsed is None:
            errors.append(
                ValidationErrorItem(
                    code="hard_policy_malformed",
                    message="tenant hard policy is malformed; turn fails closed",
                    path=f"hard_policies[{index}]",
                    retryable=False,
                )
            )
            continue
        policies.append(parsed)
    return policies, errors


def _parse_hard_policy(item: object) -> HardPolicy | None:
    if not isinstance(item, dict):
        return None
    policy_id = str(item.get("policy_id") or "").strip()
    patterns = item.get("trigger_patterns")
    requires = item.get("requires_any")
    if not policy_id or not isinstance(patterns, list) or not isinstance(requires, list):
        return None
    cleaned_patterns = [str(p) for p in patterns if str(p).strip()]
    cleaned_requires = [str(r) for r in requires if str(r).strip()]
    if not cleaned_patterns or not cleaned_requires:
        return None
    for pattern in cleaned_patterns:
        try:
            re.compile(pattern)
        except re.error:
            return None
    return HardPolicy(
        policy_id=policy_id,
        description=str(item.get("description") or policy_id),
        trigger_patterns=tuple(cleaned_patterns),
        requires_any=tuple(cleaned_requires),
        error_code=str(item.get("error_code")) if item.get("error_code") else None,
    )


def _policy_triggered(policy: HardPolicy, texts: list[str]) -> bool:
    for pattern in policy.trigger_patterns:
        compiled = re.compile(pattern, re.IGNORECASE)
        if any(compiled.search(text) for text in texts if text):
            return True
    return False


def _policy_supported(
    policy: HardPolicy,
    output: LLMAgentTurnOutput,
    context: AgentContextPackage,
) -> bool:
    available_refs = _available_source_refs(context)
    for requirement in policy.requires_any:
        kind, _, value = requirement.partition(":")
        if kind == "tool" and value and _tool_succeeded(context, value):
            return True
        if kind == "basis" and value:
            for claim in output.claims:
                if (
                    claim.basis == value
                    and claim.source_refs
                    and all(ref in available_refs for ref in claim.source_refs)
                ):
                    return True
    return False


def _tool_binding_errors(
    output: LLMAgentTurnOutput,
    context: AgentContextPackage,
) -> list[ValidationErrorItem]:
    bound_names = {
        str(schema.get("tool_name") or schema.get("name") or schema.get("key"))
        for schema in context.tool_schemas
        if isinstance(schema, dict) and schema.get("enabled", True) is not False
    }
    errors: list[ValidationErrorItem] = []
    for index, proposal in enumerate(output.tool_requests):
        if bound_names and proposal.tool_name not in bound_names:
            errors.append(
                _error(
                    "tool_not_bound",
                    "tool request requires an enabled bound tool schema",
                    path=f"tool_requests[{index}].tool_name",
                )
            )
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
    """Accepts both bare ids (back-compat) and the F19 prefixed forms:
    tool:<tool_name>, kb:<source_id>, contact_field:<field_key>,
    simulated_field:<field_key>, transcript:latest_customer_message."""
    refs: set[str] = set()
    for item in context.tool_results:
        for value in _ids_from_item(item, keys=("tool_name", "name", "tool_id", "id")):
            refs.add(value)
            refs.add(f"tool:{value}")
    for item in context.retrieved_context:
        for value in _ids_from_item(item, keys=("source_id", "id", "title")):
            refs.add(value)
            refs.add(f"kb:{value}")
    for item in context.knowledge_bindings:
        for value in _ids_from_item(item, keys=("source_id", "id", "name")):
            refs.add(value)
            refs.add(f"kb:{value}")
    for item in context.field_policies:
        if isinstance(item, dict):
            key = item.get("field_key") or item.get("key")
            if key:
                refs.add(f"contact_field:{key}")
                refs.add(f"simulated_field:{key}")
    contact_state = context.agent_identity.get("contact_state") or {}
    if isinstance(contact_state, dict):
        for key in contact_state:
            refs.add(f"contact_field:{key}")
            refs.add(f"simulated_field:{key}")
    refs.add("transcript:latest_customer_message")
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
    "HardPolicy",
    "RespondStyleTurnValidator",
    "RespondStyleTurnValidatorConfig",
    "default_hard_policies",
]
