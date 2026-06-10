from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from pydantic import BaseModel

from atendia.agent_runtime.business_events import derive_business_event_bundle
from atendia.agent_runtime.schemas import (
    AdvisorBrainDecision,
    ToolExecutionResult,
    TurnContext,
    TurnOutput,
)
from atendia.agent_runtime.state_writer import StateWriteResult

TRACE_VERSION = "1.0"
VISIBLE_TEXT_AUTHORITY = "TurnOutput.final_message"
TOOL_VISIBLE_TEXT_ALLOWED = False


def attach_universal_turn_trace(
    *,
    context: TurnContext,
    decision: AdvisorBrainDecision,
    tool_results: list[ToolExecutionResult],
    state_write_result: StateWriteResult,
    policy_warnings: list[dict[str, str]],
    output: TurnOutput,
) -> TurnOutput:
    """Attach a stable audit view without mutating the raw trace keys."""

    trace = dict(output.trace_metadata)
    if "business_events" not in trace or "workflow_results" not in trace:
        event_bundle = derive_business_event_bundle(
            context=context,
            decision=decision,
            tool_results=tool_results,
            state_write_result=state_write_result,
            output=output.model_copy(update={"trace_metadata": trace}),
        )
        payload = event_bundle.trace_payload()
        trace.setdefault("business_events", payload["business_events"])
        trace.setdefault("workflow_results", payload["workflow_results"])
    traced_output = output.model_copy(update={"trace_metadata": trace})
    trace["universal_turn_trace"] = build_universal_turn_trace(
        context=context,
        decision=decision,
        tool_results=tool_results,
        state_write_result=state_write_result,
        policy_warnings=policy_warnings,
        output=traced_output,
    )
    return output.model_copy(update={"trace_metadata": trace})


def build_universal_turn_trace(
    *,
    context: TurnContext,
    decision: AdvisorBrainDecision,
    tool_results: list[ToolExecutionResult],
    state_write_result: StateWriteResult,
    policy_warnings: list[dict[str, str]],
    output: TurnOutput,
) -> dict[str, Any]:
    raw_trace = output.trace_metadata
    mandatory_decisions = _list_of_dicts(raw_trace.get("mandatory_tool_decisions"))
    guards = _guard_views(raw_trace)
    tool_trace = [
        _tool_result_view(
            context=context,
            result=result,
            mandatory_tool_decisions=mandatory_decisions,
            state_writer_decisions=state_write_result.decisions,
        )
        for result in tool_results
    ]
    lifecycle = _lifecycle_view(context, decision, state_write_result)
    state_writer_summary = {
        **state_write_result.summary,
        "safe_mode": context.tenant_config.safe_mode,
    }

    return {
        "trace_version": TRACE_VERSION,
        "turn_id": _turn_id(context=context, output=output),
        "tenant_id": context.tenant_id,
        "agent_id": _agent_id(context),
        "conversation_id": context.conversation_id,
        "contact_id": context.customer.id,
        "domain": _domain(context),
        "input": _input_view(context),
        "gpt_understanding": _gpt_understanding(decision),
        "gpt_proposed": _gpt_proposed(decision),
        "mandatory_tool_decisions": mandatory_decisions,
        "tool_results": tool_trace,
        "atendia_validation": {
            "mandatory_tool_decisions": mandatory_decisions,
            "state_writer_decisions": list(state_write_result.decisions),
            "state_writer": {
                "accepted": list(state_write_result.accepted),
                "blocked": list(state_write_result.blocked),
                "needs_review": list(state_write_result.needs_review),
                "summary": state_writer_summary,
            },
            "guards": guards,
            "policy_warnings": _list_of_dicts(
                raw_trace.get("policy_warnings"),
                fallback=policy_warnings,
            ),
            "safe_mode": context.tenant_config.safe_mode,
        },
        "state_changes": {
            "field_updates": [_jsonable(update) for update in output.field_updates],
            "accepted": list(state_write_result.accepted),
            "blocked": list(state_write_result.blocked),
            "needs_review": list(state_write_result.needs_review),
            "decisions": list(state_write_result.decisions),
            "invalidated_fields": list(state_write_result.invalidated_fields),
            "summary": state_writer_summary,
        },
        "lifecycle": lifecycle,
        "business_events": _list_of_dicts(raw_trace.get("business_events")),
        "workflow_results": _list_of_dicts(raw_trace.get("workflow_results")),
        "guards": guards,
        "provider": _provider_view(raw_trace),
        "validated_response_plan": _dict(raw_trace.get("validated_response_plan")),
        "human_response_composer": _dict(raw_trace.get("human_response_composer")),
        "final_output": {
            "final_message": output.final_message,
            "source": VISIBLE_TEXT_AUTHORITY,
            "visible": True,
            "visible_to_customer": True,
            "confidence": output.confidence,
            "needs_human": output.needs_human,
            "risk_flags": list(output.risk_flags),
        },
        "audit": {
            "safe_mode": context.tenant_config.safe_mode,
            "tenant_domain_contract": _tenant_domain_contract_view(context, raw_trace),
            "visible_text_authority": VISIBLE_TEXT_AUTHORITY,
            "tool_visible_text_allowed": TOOL_VISIBLE_TEXT_ALLOWED,
            "raw_trace_preserved": True,
        },
    }


def why_answer_from_universal_trace(trace: dict[str, Any]) -> str:
    """Return a non-technical explanation of why the final answer was produced."""

    final_output = _dict(trace.get("final_output"))
    validation = _dict(trace.get("atendia_validation"))
    state_writer = _dict(validation.get("state_writer"))
    blocked_count = len(_list(state_writer.get("blocked")))
    review_count = len(_list(state_writer.get("needs_review")))
    guard_results = [str(item.get("result")) for item in _list_of_dicts(trace.get("guards"))]

    parts = ["Se respondio con el mensaje final validado por AtendIA."]
    if "rewrote" in guard_results or "blocked" in guard_results:
        parts.append("Algunos datos sensibles se ajustaron o detuvieron porque faltaba validacion.")
    if blocked_count:
        parts.append("No se guardaron cambios que no cumplieron las reglas del tenant.")
    if review_count:
        parts.append("Algunos datos quedaron para revision antes de aplicarse.")
    if not final_output.get("visible"):
        parts.append("No hubo texto visible para el cliente.")
    return " ".join(parts)


def _tool_result_view(
    *,
    context: TurnContext,
    result: ToolExecutionResult,
    mandatory_tool_decisions: list[dict[str, Any]],
    state_writer_decisions: list[dict[str, Any]],
) -> dict[str, Any]:
    data = _dict(result.data)
    trace_metadata = _dict(result.trace_metadata)
    return {
        "tool_id": result.tool_name,
        "status": result.status,
        "tenant_id": _tool_tenant_id(context, data, trace_metadata),
        "safe_inputs": _safe_tool_inputs(trace_metadata),
        "structured_output": _jsonable(data),
        "citations": _citations(data),
        "used_for": _tool_used_for(
            result.tool_name,
            mandatory_tool_decisions=mandatory_tool_decisions,
            state_writer_decisions=state_writer_decisions,
        ),
        "visible_text_allowed": TOOL_VISIBLE_TEXT_ALLOWED,
        "error": result.error,
        "trace_metadata": _jsonable(trace_metadata),
    }


def _tool_used_for(
    tool_id: str,
    *,
    mandatory_tool_decisions: list[dict[str, Any]],
    state_writer_decisions: list[dict[str, Any]],
) -> list[str]:
    uses: list[str] = []
    for decision in mandatory_tool_decisions:
        if tool_id in _list(decision.get("matched_tools")):
            topic = str(decision.get("topic") or "mandatory_tool_requirement")
            uses.append(f"mandatory_tool:{topic}")
    if any(str(decision.get("source") or "") == tool_id for decision in state_writer_decisions):
        uses.append("state_write_validation")
    if tool_id == "quote.resolve":
        uses.append("quote_validation")
    return _dedupe(uses)


def _guard_views(raw_trace: dict[str, Any]) -> list[dict[str, Any]]:
    guards: list[dict[str, Any]] = []
    mandatory = _dict(raw_trace.get("mandatory_tool_guard"))
    if mandatory:
        guards.append(
            {
                "guard_id": "mandatory_tool_guard",
                "result": _mandatory_guard_result(mandatory),
                "action": mandatory.get("action"),
                "reason": _first_blocking_reason(_list_of_dicts(mandatory.get("decisions"))),
                "details": _jsonable(mandatory),
            }
        )
    for key in ("quote_safety", "conversation_progress_guard"):
        payload = _dict(raw_trace.get(key))
        if payload:
            guards.append(
                {
                    "guard_id": key,
                    "result": _guard_result_from_payload(payload),
                    "action": payload.get("action"),
                    "reason": payload.get("reason") or _first(_list(payload.get("failures"))),
                    "details": _guard_details(payload),
                }
            )
    normalizer = _dict(raw_trace.get("conversation_progress_normalizer"))
    if normalizer:
        guards.append(
            {
                "guard_id": "conversation_progress_normalizer",
                "result": "rewrote",
                "action": normalizer.get("action"),
                "reason": normalizer.get("reason"),
                "details": _jsonable(normalizer),
            }
        )
    guard_result = _dict(raw_trace.get("guard_result"))
    if guard_result and "quote_safety" not in {item["guard_id"] for item in guards}:
        guards.append(
            {
                "guard_id": "guard_result",
                "result": _guard_result_from_payload(guard_result),
                "action": guard_result.get("action"),
                "reason": guard_result.get("reason") or _first(_list(guard_result.get("failures"))),
                "details": _guard_details(guard_result),
            }
        )
    return guards


def _guard_details(payload: dict[str, Any]) -> dict[str, Any]:
    allowed_keys = {
        "action",
        "allowed",
        "failures",
        "has_visible_quote",
        "metrics",
        "mode",
        "reason",
        "repeat_detected",
        "repeat_type",
        "visible_price_detected",
    }
    return {
        key: _jsonable(value)
        for key, value in payload.items()
        if key in allowed_keys and value is not None
    }


def _mandatory_guard_result(payload: dict[str, Any]) -> str:
    if payload.get("action") == "rewritten":
        return "rewrote"
    decisions = _list_of_dicts(payload.get("decisions"))
    if any(decision.get("blocking") for decision in decisions):
        return "blocked"
    return "passed"


def _guard_result_from_payload(payload: dict[str, Any]) -> str:
    action = str(payload.get("action") or "")
    if action in {"rewritten", "sanitized"}:
        return "rewrote"
    if action == "shadow":
        return "warned"
    if payload.get("allowed") is False:
        return "blocked"
    if payload.get("allowed") is True or action == "allowed":
        return "passed"
    return "warned"


def _lifecycle_view(
    context: TurnContext,
    decision: AdvisorBrainDecision,
    state_write_result: StateWriteResult,
) -> dict[str, Any]:
    proposed = [
        _jsonable(change)
        for change in decision.proposed_state_changes
        if change.target == "lifecycle"
    ]
    proposed_stage = _first_lifecycle_value(proposed, "target_stage", "stage", "key")
    proposed_status = _first_lifecycle_value(proposed, "target_status", "status")
    accepted = (
        _jsonable(state_write_result.lifecycle_update)
        if state_write_result.lifecycle_update
        else None
    )
    accepted_payload = _dict(accepted)
    return {
        "stage_before": context.lifecycle.stage,
        "status_before": context.lifecycle.status,
        "stage_proposed": proposed_stage,
        "status_proposed": proposed_status,
        "stage_after": accepted_payload.get("target_stage") if accepted_payload else None,
        "status_after": accepted_payload.get("target_status") if accepted_payload else None,
        "proposed_updates": proposed,
        "validated_update": accepted,
    }


def _first_lifecycle_value(
    proposals: list[Any],
    *keys: str,
) -> Any:
    for proposal in proposals:
        payload = _dict(proposal)
        value = payload.get("value")
        value_payload = _dict(value)
        for key in keys:
            if payload.get(key):
                return payload[key]
            if value_payload.get(key):
                return value_payload[key]
    return None


def _gpt_understanding(decision: AdvisorBrainDecision) -> dict[str, Any]:
    return {
        "understanding": decision.understanding,
        "customer_goal": decision.customer_goal,
        "conversation_goals": list(decision.conversation_goals),
        "known_facts": _jsonable(decision.known_facts),
        "missing_facts": list(decision.missing_facts),
        "next_best_action": decision.next_best_action,
        "response_plan": decision.response_plan,
        "confidence": decision.confidence,
        "needs_human": decision.needs_human,
        "risk_flags": list(decision.risk_flags),
        "latest_customer_act": decision.latest_customer_act,
        "new_information_detected": decision.new_information_detected,
    }


def _gpt_proposed(decision: AdvisorBrainDecision) -> dict[str, Any]:
    return {
        "state_changes": [_jsonable(change) for change in decision.proposed_state_changes],
        "required_tools": [_jsonable(tool) for tool in decision.required_tools],
        "lifecycle_updates": [
            _jsonable(change)
            for change in decision.proposed_state_changes
            if change.target == "lifecycle"
        ],
        "customer_visible_copy": None,
        "visible_text_allowed": False,
        "metadata": _jsonable(decision.metadata),
    }


def _input_view(context: TurnContext) -> dict[str, Any]:
    return {
        "inbound_text": context.inbound_text,
        "message_count": len(context.messages),
        "metadata": _jsonable(context.metadata),
    }


def _provider_view(raw_trace: dict[str, Any]) -> dict[str, Any]:
    return {
        "provider": raw_trace.get("provider"),
        "model": raw_trace.get("model"),
        "reliability": _jsonable(raw_trace.get("provider_reliability") or {}),
        "created_at": raw_trace.get("created_at"),
    }


def _tenant_domain_contract_view(
    context: TurnContext,
    raw_trace: dict[str, Any],
) -> dict[str, Any]:
    context_metadata = _dict(context.metadata.get("tenant_domain_contract"))
    trace_metadata = _dict(raw_trace.get("tenant_domain_contract"))
    config_metadata = _dict(context.tenant_config.tenant_domain_contract)
    return {
        **_jsonable(config_metadata),
        **_jsonable(context_metadata),
        **_jsonable(trace_metadata),
        "domain": _domain(context),
        "safe_mode": context.tenant_config.safe_mode,
    }


def _domain(context: TurnContext) -> str | None:
    return (
        context.tenant_config.domain
        or _dict(context.metadata.get("tenant_domain_contract")).get("domain")
    )


def _agent_id(context: TurnContext) -> str | None:
    if context.active_agent and context.active_agent.id:
        return context.active_agent.id
    if context.metadata.get("agent_id"):
        return str(context.metadata["agent_id"])
    contract = _dict(context.tenant_config.tenant_domain_contract)
    if contract.get("agent_id"):
        return str(contract["agent_id"])
    return None


def _turn_id(*, context: TurnContext, output: TurnOutput) -> str:
    for value in (
        context.metadata.get("turn_id"),
        context.metadata.get("message_id"),
        context.metadata.get("inbound_message_id"),
        output.trace_metadata.get("trace_id"),
    ):
        if value:
            return str(value)
    turn_number = context.metadata.get("turn_number") or "unknown"
    return f"{context.conversation_id}:{turn_number}"


def _tool_tenant_id(
    context: TurnContext,
    data: dict[str, Any],
    trace_metadata: dict[str, Any],
) -> str | None:
    if trace_metadata.get("tenant_id") is not None:
        return str(trace_metadata["tenant_id"])
    found = _first_tenant_id(data)
    return str(found) if found is not None else context.tenant_id


def _first_tenant_id(value: Any) -> Any:
    if isinstance(value, dict):
        for key, nested in value.items():
            if str(key) in {"tenant_id", "tenantId"} and nested is not None:
                return nested
            found = _first_tenant_id(nested)
            if found is not None:
                return found
    if isinstance(value, list):
        for nested in value:
            found = _first_tenant_id(nested)
            if found is not None:
                return found
    return None


def _safe_tool_inputs(trace_metadata: dict[str, Any]) -> dict[str, Any]:
    for key in ("safe_inputs", "inputs", "input"):
        value = trace_metadata.get(key)
        if isinstance(value, dict):
            return _jsonable(value)
    return {}


def _citations(data: dict[str, Any]) -> list[Any]:
    for key in ("citations", "sources", "evidence"):
        value = data.get(key)
        if isinstance(value, list):
            return _jsonable(value)
    return []


def _list_of_dicts(
    value: Any,
    *,
    fallback: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    source = value if isinstance(value, list) else fallback or []
    return [_jsonable(item) for item in source if isinstance(_jsonable(item), dict)]


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if is_dataclass(value) and not isinstance(value, type):
        return _jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): _jsonable(nested) for key, nested in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, tuple | set | frozenset):
        return [_jsonable(item) for item in value]
    return value


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _first(values: list[Any]) -> Any:
    return values[0] if values else None


def _first_blocking_reason(decisions: list[dict[str, Any]]) -> str | None:
    for decision in decisions:
        if decision.get("blocking"):
            return str(decision.get("reason") or decision.get("status") or "")
    return None


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result


__all__ = [
    "TOOL_VISIBLE_TEXT_ALLOWED",
    "TRACE_VERSION",
    "VISIBLE_TEXT_AUTHORITY",
    "attach_universal_turn_trace",
    "build_universal_turn_trace",
    "why_answer_from_universal_trace",
]
