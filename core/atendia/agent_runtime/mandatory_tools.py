from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from atendia.agent_runtime.quote_safety import visible_quote_signal
from atendia.agent_runtime.schemas import (
    AdvisorBrainDecision,
    AdvisorBrainStateChange,
    ToolExecutionResult,
    TurnContext,
    TurnOutput,
)

RequirementStatus = Literal["required", "executed", "missing", "blocked", "not_applicable"]
GuardAction = Literal["recorded", "rewritten"]


_REQUIREMENTS_RE = (
    r"\b(?:requisit(?:o|os)|document(?:o|os)|papeleria|papeles|ine|"
    r"comprobante(?:s)?|identificacion|domicilio)\b"
)
_POLICY_RE = (
    r"\b(?:politica|restriccion(?:es)?|aprobacion|aprobar|aprueba|aprobado|"
    r"garantia|cobertura|buro|rechazo|rechazado)\b"
)
_CATALOG_RE = r"\b(?:producto|servicio|modelo|catalogo|disponibilidad|ficha|listing)\b"

_DEFAULT_TOOL_ALIASES: dict[str, frozenset[str]] = {
    "catalog.search": frozenset({"catalog.search", "catalog.lookup", "search_catalog"}),
    "quote.resolve": frozenset({"quote.resolve"}),
    "requirements.lookup": frozenset(
        {"requirements.lookup", "requirements.resolve", "lookup_requirements"}
    ),
    "faq.lookup": frozenset({"faq.lookup", "faq.resolve", "lookup_faq"}),
    "policy.lookup": frozenset({"policy.lookup"}),
    "document.check": frozenset({"document.check", "vision.document_check"}),
    "availability.check": frozenset({"availability.check"}),
    "booking.create": frozenset({"booking.create"}),
}


@dataclass(frozen=True)
class ToolRequirementRule:
    rule_id: str
    topic: str
    tool_id: str
    reason: str
    trigger_source: str
    blocking_scopes: tuple[str, ...]
    fallback: str
    alternative_tool_ids: tuple[str, ...] = ()
    final_message_pattern: str | None = None
    response_plan_pattern: str | None = None
    state_change_key_patterns: tuple[str, ...] = ()
    state_change_metadata_keys: tuple[str, ...] = ()
    lifecycle_stage_pattern: str | None = None
    uses_price_signal: bool = False

    @property
    def accepted_tool_ids(self) -> tuple[str, ...]:
        return (self.tool_id, *self.alternative_tool_ids)


@dataclass(frozen=True)
class ToolRequirementDecision:
    rule_id: str
    tool_id: str
    topic: str
    required: bool
    reason: str
    trigger_source: str
    blocking_scopes: list[str]
    status: RequirementStatus
    blocking: bool
    fallback: str
    matched_tools: list[str] = field(default_factory=list)
    invalid_tool_results: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MandatoryToolEvaluation:
    decisions: list[ToolRequirementDecision] = field(default_factory=list)
    invalid_tool_results: list[dict[str, Any]] = field(default_factory=list)

    @property
    def blocking_decisions(self) -> list[ToolRequirementDecision]:
        return [decision for decision in self.decisions if decision.blocking]

    @property
    def blocks_final_message(self) -> bool:
        return any(
            "final_message" in decision.blocking_scopes
            for decision in self.blocking_decisions
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "decisions": [decision.to_dict() for decision in self.decisions],
            "invalid_tool_results": list(self.invalid_tool_results),
            "blocks_final_message": self.blocks_final_message,
        }


@dataclass(frozen=True)
class MandatoryToolApplyResult:
    output: TurnOutput
    evaluation: MandatoryToolEvaluation
    action: GuardAction


class MandatoryToolGuard:
    """Enforce tenant-declared tool requirements for sensitive operational facts."""

    def __init__(
        self,
        rules: list[ToolRequirementRule] | None = None,
        *,
        tool_aliases: dict[str, set[str] | frozenset[str]] | None = None,
    ) -> None:
        self._rules = list(rules or default_tool_requirement_rules())
        aliases = {key: set(values) for key, values in _DEFAULT_TOOL_ALIASES.items()}
        for key, values in (tool_aliases or {}).items():
            aliases.setdefault(key, set()).update(str(value) for value in values)
        self._tool_aliases = {key: frozenset(values) for key, values in aliases.items()}

    def evaluate(
        self,
        *,
        context: TurnContext,
        decision: AdvisorBrainDecision,
        tool_results: list[ToolExecutionResult] | None = None,
        output: TurnOutput | None = None,
    ) -> MandatoryToolEvaluation:
        tool_results = list(tool_results or [])
        tool_aliases = _tool_aliases_for_context(context, self._tool_aliases)
        invalid_results = _invalid_tool_results(context, tool_results, tool_aliases)
        decisions: list[ToolRequirementDecision] = []
        seen_rule_ids: set[str] = set()

        for required_tool in decision.required_tools:
            if not required_tool.required:
                continue
            canonical_tool = _canonical_tool_name(required_tool.name, tool_aliases)
            rule = ToolRequirementRule(
                rule_id=f"advisor_required:{canonical_tool}",
                topic="advisor_required_tool",
                tool_id=canonical_tool,
                reason=required_tool.reason or "advisor_required_tool",
                trigger_source="advisor_brain.required_tools",
                blocking_scopes=("tool",),
                fallback="skip_untrusted_tool_result",
            )
            decisions.append(
                self._decision_for_rule(
                    rule,
                    tool_results=tool_results,
                    invalid_tool_results=invalid_results,
                    tool_aliases=tool_aliases,
                )
            )
            seen_rule_ids.add(rule.rule_id)

        for rule in [*self._rules, *_rules_from_tenant_config(context)]:
            if rule.rule_id in seen_rule_ids:
                continue
            if not _rule_matches(rule, decision=decision, output=output):
                continue
            decisions.append(
                self._decision_for_rule(
                    rule,
                    tool_results=tool_results,
                    invalid_tool_results=invalid_results,
                    tool_aliases=tool_aliases,
                )
            )
            seen_rule_ids.add(rule.rule_id)
        return MandatoryToolEvaluation(decisions=decisions, invalid_tool_results=invalid_results)

    def apply(
        self,
        *,
        context: TurnContext,
        decision: AdvisorBrainDecision,
        tool_results: list[ToolExecutionResult] | None,
        output: TurnOutput,
        pre_evaluation: MandatoryToolEvaluation | None = None,
        defer_quote_final_message: bool = False,
    ) -> MandatoryToolApplyResult:
        evaluation = self.evaluate(
            context=context,
            decision=decision,
            tool_results=tool_results,
            output=output,
        )
        decisions = _merge_decisions(pre_evaluation, evaluation)
        evaluation = MandatoryToolEvaluation(
            decisions=decisions,
            invalid_tool_results=[
                *(pre_evaluation.invalid_tool_results if pre_evaluation else []),
                *evaluation.invalid_tool_results,
            ],
        )
        blockers = [
            blocker
            for blocker in evaluation.blocking_decisions
            if not (
                defer_quote_final_message
                and blocker.tool_id == "quote.resolve"
                and "final_message" in blocker.blocking_scopes
            )
            and not (
                blocker.tool_id == "requirements.lookup"
                and _credit_plan_needs_clarification(tool_results or [])
            )
            and not (
                blocker.tool_id == "requirements.lookup"
                and _has_validated_requirements_facts(output)
            )
        ]
        trace = {
            **output.trace_metadata,
            "mandatory_tool_decisions": [item.to_dict() for item in evaluation.decisions],
            "mandatory_tool_guard": {
                **evaluation.to_dict(),
                "action": (
                    "rewritten" if blockers and evaluation.blocks_final_message else "recorded"
                ),
            },
        }
        if not blockers or not any("final_message" in item.blocking_scopes for item in blockers):
            return MandatoryToolApplyResult(
                output=output.model_copy(update={"trace_metadata": trace}),
                evaluation=evaluation,
                action="recorded",
            )

        message = _safe_fallback_for_blockers(blockers)
        safe_output = output.model_copy(
            update={
                "final_message": message,
                "confidence": min(output.confidence, 0.5),
                "needs_human": True,
                "risk_flags": _append_unique(
                    [*output.risk_flags, "mandatory_tool_missing"],
                    f"mandatory_tool_missing:{blockers[0].tool_id}",
                ),
                "trace_metadata": trace,
            }
        )
        return MandatoryToolApplyResult(
            output=safe_output,
            evaluation=evaluation,
            action="rewritten",
        )

    def _decision_for_rule(
        self,
        rule: ToolRequirementRule,
        *,
        tool_results: list[ToolExecutionResult],
        invalid_tool_results: list[dict[str, Any]],
        tool_aliases: dict[str, frozenset[str]],
    ) -> ToolRequirementDecision:
        accepted_names = {
            alias
            for tool_id in rule.accepted_tool_ids
            for alias in _aliases_for_tool(tool_id, tool_aliases)
        }
        invalid_for_rule = [
            item
            for item in invalid_tool_results
            if item.get("canonical_tool_name") in rule.accepted_tool_ids
            or item.get("tool_name") in accepted_names
        ]
        matched = [
            result.tool_name
            for result in tool_results
            if result.tool_name in accepted_names
            and result.status == "succeeded"
            and not _is_invalid_result(result, invalid_for_rule)
        ]
        if matched:
            status: RequirementStatus = "executed"
        elif invalid_for_rule:
            status = "blocked"
        else:
            status = "missing"
        return ToolRequirementDecision(
            rule_id=rule.rule_id,
            tool_id=rule.tool_id,
            topic=rule.topic,
            required=True,
            reason=rule.reason,
            trigger_source=rule.trigger_source,
            blocking_scopes=list(rule.blocking_scopes),
            status=status,
            blocking=status in {"missing", "blocked"},
            fallback=rule.fallback,
            matched_tools=matched,
            invalid_tool_results=invalid_for_rule,
        )


def default_tool_requirement_rules() -> list[ToolRequirementRule]:
    return [
        ToolRequirementRule(
            rule_id="final_message_mentions_price",
            topic="offer_or_quote",
            tool_id="quote.resolve",
            reason="final_message_mentions_price",
            trigger_source="final_message",
            blocking_scopes=("final_message", "state_write", "workflow_event"),
            fallback="ask_clarifying_or_handoff",
            uses_price_signal=True,
            response_plan_pattern=(
                r"\b(?:precio|cotizacion|cotizar|enganche|mensualidad|pago|descuento)\b"
            ),
        ),
        ToolRequirementRule(
            rule_id="requirements_requested",
            topic="requirements",
            tool_id="requirements.lookup",
            reason="final_message_requests_specific_requirements",
            trigger_source="final_message",
            blocking_scopes=("final_message", "workflow_event"),
            fallback="ask_requirements_lookup_or_handoff",
            final_message_pattern=_REQUIREMENTS_RE,
            response_plan_pattern=_REQUIREMENTS_RE,
            state_change_key_patterns=("document", "requirement", "doc_"),
            state_change_metadata_keys=("document_status", "requirements_complete"),
            lifecycle_stage_pattern=r"\b(?:requirements|documents|documentos|papeleria)\b",
        ),
        ToolRequirementRule(
            rule_id="sensitive_policy_answered",
            topic="policy_or_faq",
            tool_id="faq.lookup",
            alternative_tool_ids=("policy.lookup",),
            reason="final_message_answers_sensitive_policy",
            trigger_source="final_message",
            blocking_scopes=("final_message",),
            fallback="ask_policy_lookup_or_handoff",
            final_message_pattern=_POLICY_RE,
            response_plan_pattern=_POLICY_RE,
        ),
        ToolRequirementRule(
            rule_id="catalog_selection_answered",
            topic="catalog_or_listing",
            tool_id="catalog.search",
            reason="catalog_or_listing_fact_requires_catalog_tool",
            trigger_source="advisor_or_tenant_config",
            blocking_scopes=("state_write",),
            fallback="skip_untrusted_catalog_fact",
            state_change_metadata_keys=("canonical_product_ref", "catalog_result"),
            response_plan_pattern=_CATALOG_RE,
        ),
    ]


def _rule_matches(
    rule: ToolRequirementRule,
    *,
    decision: AdvisorBrainDecision,
    output: TurnOutput | None,
) -> bool:
    has_matching_state_change = any(
        _state_change_matches(rule, change) for change in decision.proposed_state_changes
    )
    if (
        rule.topic in {"requirements", "document_status"}
        and _is_document_future_promise(decision)
        and not has_matching_state_change
    ):
        return False
    if _is_clarification_only_turn(decision):
        return False
    final_message = output.final_message if output is not None else ""
    if rule.uses_price_signal and (
        visible_quote_signal(final_message)
        or _pattern_matches(rule.response_plan_pattern, decision.response_plan)
    ):
        return True
    if output is not None and _pattern_matches(rule.final_message_pattern, final_message):
        return True
    if _pattern_matches(rule.response_plan_pattern, decision.response_plan):
        return True
    return any(_state_change_matches(rule, change) for change in decision.proposed_state_changes)


def _is_clarification_only_turn(decision: AdvisorBrainDecision) -> bool:
    return bool(decision.should_ask_question or decision.missing_facts) and not (
        decision.required_tools or decision.proposed_state_changes
    )


def _is_document_future_promise(decision: AdvisorBrainDecision) -> bool:
    text = " ".join(
        [
            str(decision.customer_goal or ""),
            str(decision.understanding or ""),
            str(decision.response_plan or ""),
            str(decision.metadata.get("income") or ""),
        ]
    ).casefold()
    return any(
        token in text
        for token in (
            "document_future_promise",
            "will_send_document",
            "promesa_documento",
            "send_document_later",
            "mandar ine despues",
            "mandar ine después",
        )
    )


def _state_change_matches(rule: ToolRequirementRule, change: AdvisorBrainStateChange) -> bool:
    key = str(change.key or "")
    folded_key = key.casefold()
    if any(pattern.casefold() in folded_key for pattern in rule.state_change_key_patterns):
        return True
    if any(
        str(change.metadata.get(name) or "").strip()
        for name in rule.state_change_metadata_keys
    ):
        return True
    if change.target == "lifecycle":
        stage = key or _stage_from_value(change.value)
        return _pattern_matches(rule.lifecycle_stage_pattern, stage)
    return False


def _rules_from_tenant_config(context: TurnContext) -> list[ToolRequirementRule]:
    raw_rules = _dict(context.tenant_config.ruleset.get("mandatory_tools")).get("rules")
    if not isinstance(raw_rules, list):
        raw_rules = []
    parsed: list[ToolRequirementRule] = []
    for raw in raw_rules:
        if not isinstance(raw, dict):
            continue
        rule_id = str(raw.get("rule_id") or "").strip()
        tool_id = str(raw.get("tool_id") or "").strip()
        topic = str(raw.get("topic") or "tenant_configured_tool").strip()
        if not rule_id or not tool_id:
            continue
        parsed.append(
            ToolRequirementRule(
                rule_id=rule_id,
                topic=topic,
                tool_id=tool_id,
                reason=str(raw.get("reason") or rule_id),
                trigger_source=str(raw.get("trigger_source") or "tenant_config"),
                blocking_scopes=tuple(
                    str(item)
                    for item in _list(raw.get("blocking_scopes"))
                    if str(item).strip()
                )
                or ("final_message",),
                fallback=str(raw.get("fallback") or "ask_clarifying_or_handoff"),
                alternative_tool_ids=tuple(
                    str(item)
                    for item in _list(raw.get("alternative_tool_ids"))
                    if str(item).strip()
                ),
                final_message_pattern=_optional_str(raw.get("final_message_pattern")),
                response_plan_pattern=_optional_str(raw.get("response_plan_pattern")),
                state_change_key_patterns=tuple(
                    str(item)
                    for item in _list(raw.get("state_change_key_patterns"))
                    if str(item).strip()
                ),
                state_change_metadata_keys=tuple(
                    str(item)
                    for item in _list(raw.get("state_change_metadata_keys"))
                    if str(item).strip()
                ),
                lifecycle_stage_pattern=_optional_str(raw.get("lifecycle_stage_pattern")),
                uses_price_signal=bool(raw.get("uses_price_signal")),
            )
        )
    return parsed


def _invalid_tool_results(
    context: TurnContext,
    tool_results: list[ToolExecutionResult],
    tool_aliases: dict[str, frozenset[str]],
) -> list[dict[str, Any]]:
    invalid: list[dict[str, Any]] = []
    tenant_id = str(context.tenant_id)
    for result in tool_results:
        ids = _tenant_ids_in_value(result.data)
        trace_tenant_id = result.trace_metadata.get("tenant_id")
        if trace_tenant_id is not None:
            ids.append(str(trace_tenant_id))
        mismatches = sorted({item for item in ids if item and item != tenant_id})
        if mismatches:
            invalid.append(
                {
                    "tool_name": result.tool_name,
                    "canonical_tool_name": _canonical_tool_name(
                        result.tool_name,
                        tool_aliases,
                    ),
                    "reason": "tenant_id_mismatch",
                    "expected_tenant_id": tenant_id,
                    "actual_tenant_ids": mismatches,
                }
            )
    return invalid


def _credit_plan_needs_clarification(tool_results: list[ToolExecutionResult]) -> bool:
    return any(
        result.tool_name == "credit_plan.resolve"
        and result.status == "succeeded"
        and bool(_dict(result.data).get("needs_clarification"))
        for result in tool_results
    )


def _has_validated_requirements_facts(output: TurnOutput) -> bool:
    trace = output.trace_metadata if isinstance(output.trace_metadata, dict) else {}
    plan = trace.get("validated_response_plan")
    if not isinstance(plan, dict):
        return False
    facts = plan.get("validated_facts")
    if not isinstance(facts, dict):
        return False
    return "requirements" in facts or "requirements_checklist" in facts


def _tenant_ids_in_value(value: Any) -> list[str]:
    ids: list[str] = []
    if isinstance(value, dict):
        for key, nested in value.items():
            if str(key) in {"tenant_id", "tenantId"} and nested is not None:
                ids.append(str(nested))
            ids.extend(_tenant_ids_in_value(nested))
    elif isinstance(value, list):
        for nested in value:
            ids.extend(_tenant_ids_in_value(nested))
    return ids


def _is_invalid_result(result: ToolExecutionResult, invalid_results: list[dict[str, Any]]) -> bool:
    return any(item.get("tool_name") == result.tool_name for item in invalid_results)


def _merge_decisions(
    pre: MandatoryToolEvaluation | None,
    post: MandatoryToolEvaluation,
) -> list[ToolRequirementDecision]:
    merged: dict[str, ToolRequirementDecision] = {}
    for evaluation in [pre, post]:
        if evaluation is None:
            continue
        for decision in evaluation.decisions:
            existing = merged.get(decision.rule_id)
            if existing is None or _status_rank(decision.status) > _status_rank(existing.status):
                merged[decision.rule_id] = decision
    return list(merged.values())


def _status_rank(status: str) -> int:
    return {"not_applicable": 0, "executed": 1, "required": 2, "missing": 3, "blocked": 4}.get(
        status,
        0,
    )


def _safe_fallback_for_blockers(blockers: list[ToolRequirementDecision]) -> str:
    tool_ids = {blocker.tool_id for blocker in blockers}
    if "requirements.lookup" in tool_ids:
        return (
            "Necesito consultar los requisitos vigentes antes de pedirte documentos "
            "concretos. Te lo reviso para darte la lista correcta."
        )
    if "availability.check" in tool_ids:
        return (
            "Necesito revisar la disponibilidad antes de confirmar horarios o citas. "
            "Lo valido para darte una respuesta correcta."
        )
    if "booking.create" in tool_ids:
        return (
            "Necesito confirmar la cita con la herramienta correspondiente antes de "
            "darla por agendada."
        )
    if "faq.lookup" in tool_ids or "policy.lookup" in tool_ids:
        return (
            "Necesito revisar la politica correspondiente antes de darte una respuesta "
            "definitiva. Lo valido para no pasarte informacion incorrecta."
        )
    if "quote.resolve" in tool_ids:
        return (
            "Necesito confirmar la cotizacion del sistema antes de darte precio o pagos. "
            "Te lo reviso para pasarte el dato correcto."
        )
    return "Necesito validar ese dato con la herramienta correspondiente antes de confirmarlo."


def _pattern_matches(pattern: str | None, value: Any) -> bool:
    if not pattern:
        return False
    try:
        return bool(re.search(pattern, str(value or ""), re.IGNORECASE))
    except re.error:
        return False


def _stage_from_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("target_stage", "stage"):
            if value.get(key):
                return str(value[key])
    return ""


def _append_unique(values: list[str], item: str) -> list[str]:
    return values if item in values else [*values, item]


def _tool_aliases_for_context(
    context: TurnContext,
    base_aliases: dict[str, frozenset[str]],
) -> dict[str, frozenset[str]]:
    merged: dict[str, set[str]] = {key: set(values) for key, values in base_aliases.items()}
    for raw_aliases in (
        context.tenant_config.tools.get("aliases"),
        context.tenant_config.tools.get("tool_aliases"),
        _dict(context.tenant_config.ruleset.get("mandatory_tools")).get("tool_aliases"),
    ):
        if not isinstance(raw_aliases, dict):
            continue
        for key, value in raw_aliases.items():
            if isinstance(value, str):
                merged.setdefault(value, set()).add(str(key))
                continue
            values = [str(item) for item in _list(value) if str(item).strip()]
            if values:
                merged.setdefault(str(key), set()).update(values)
    for tool_id, metadata in context.tenant_config.tool_metadata.items():
        if not isinstance(metadata, dict):
            continue
        aliases = [str(item) for item in _list(metadata.get("aliases")) if str(item).strip()]
        if aliases:
            merged.setdefault(str(tool_id), set()).update(aliases)
    return {key: frozenset({key, *values}) for key, values in merged.items()}


def _aliases_for_tool(
    tool_id: str,
    tool_aliases: dict[str, frozenset[str]],
) -> frozenset[str]:
    canonical = _canonical_tool_name(tool_id, tool_aliases)
    return frozenset({canonical, *tool_aliases.get(canonical, frozenset())})


def _canonical_tool_name(
    name: str,
    tool_aliases: dict[str, frozenset[str]] | None = None,
) -> str:
    raw = str(name or "")
    aliases = tool_aliases or _DEFAULT_TOOL_ALIASES
    for canonical, values in aliases.items():
        if raw == canonical or raw in values:
            return canonical
    return raw


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _optional_str(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


__all__ = [
    "MandatoryToolApplyResult",
    "MandatoryToolEvaluation",
    "MandatoryToolGuard",
    "ToolRequirementDecision",
    "ToolRequirementRule",
    "default_tool_requirement_rules",
]
