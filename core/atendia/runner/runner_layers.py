from __future__ import annotations

from typing import Any

from atendia.contracts.flow_mode import FlowMode


def build_runner_layers(
    *,
    pipeline: Any,
    previous_stage: str,
    next_stage: str,
    decision_action: str,
    decision_reason: str,
    flow_mode: FlowMode,
    action_payload: dict[str, Any],
    extracted_data: dict[str, Any],
    rules_evaluated: list[dict[str, Any]] | None,
    router_trigger: str | None,
    pause_bot: bool,
    decision_debug: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create the four explicit runner layers persisted in turn traces.

    The runner already performs these phases; this object makes them
    inspectable and stable for QA, debug UI, and operators.
    """

    return {
        "data": _data_layer(
            pipeline=pipeline,
            extracted_data=extracted_data,
        ),
        "decision": _decision_layer(
            previous_stage=previous_stage,
            next_stage=next_stage,
            decision_action=decision_action,
            decision_reason=decision_reason,
            flow_mode=flow_mode,
            rules_evaluated=rules_evaluated,
            router_trigger=router_trigger,
            pause_bot=pause_bot,
            decision_debug=decision_debug or {},
        ),
        "payload": _payload_layer(action_payload),
        "explanation": _explanation_layer(
            pipeline=pipeline,
            previous_stage=previous_stage,
            next_stage=next_stage,
            decision_action=decision_action,
            decision_reason=decision_reason,
            flow_mode=flow_mode,
            extracted_data=extracted_data,
            pause_bot=pause_bot,
        ),
    }


def _data_layer(*, pipeline: Any, extracted_data: dict[str, Any]) -> dict[str, Any]:
    documents = {
        key: _unwrap(value)
        for key, value in extracted_data.items()
        if str(key).lower().startswith(("docs_", "docs."))
    }
    customer_data = {
        key: _unwrap(value)
        for key, value in extracted_data.items()
        if not str(key).lower().startswith(("docs_", "docs."))
    }
    return {
        "customer_data": customer_data,
        "extracted_data_keys": sorted(extracted_data.keys()),
        "documents": documents,
        "documents_catalog_keys": [
            str(getattr(item, "key", ""))
            for item in (getattr(pipeline, "documents_catalog", []) or [])
            if getattr(item, "key", None)
        ],
        "catalog_available": bool(getattr(pipeline, "document_requirements", None)),
    }


def _decision_layer(
    *,
    previous_stage: str,
    next_stage: str,
    decision_action: str,
    decision_reason: str,
    flow_mode: FlowMode,
    rules_evaluated: list[dict[str, Any]] | None,
    router_trigger: str | None,
    pause_bot: bool,
    decision_debug: dict[str, Any],
) -> dict[str, Any]:
    matched_rules = [
        rule.get("name") or rule.get("stage_id")
        for rule in (rules_evaluated or [])
        if rule.get("matched") is True or rule.get("passed") is True
    ]
    return {
        "stage_from": previous_stage,
        "stage_to": next_stage,
        "stage_moved": previous_stage != next_stage,
        "action": decision_action,
        "reason": decision_reason,
        "flow_mode": flow_mode.value,
        "router_trigger": router_trigger,
        "matched_rules": [item for item in matched_rules if item],
        "pause_bot": pause_bot,
        "action_before_auto_enter": decision_debug.get("action_before_auto_enter"),
        "action_after_recompute": decision_debug.get("action_after_recompute", decision_action),
        "stage_after_fsm": decision_debug.get("stage_after_fsm"),
        "stage_after_auto_enter": decision_debug.get("stage_after_auto_enter", next_stage),
        "auto_enter_rules_executed": decision_debug.get("auto_enter_rules_executed", False),
        "recomputed_after_stage_change": decision_debug.get("recomputed_after_stage_change", False),
        "recompute_reason": decision_debug.get("recompute_reason"),
        "executed_tools": decision_debug.get("executed_tools", []),
        "tool_inputs": decision_debug.get("tool_inputs", []),
        "tool_outputs": decision_debug.get("tool_outputs", []),
        "resolver_attempts": decision_debug.get("resolver_attempts", []),
        "field_updates_proposed": decision_debug.get("field_updates_proposed", []),
        "field_updates_approved": decision_debug.get("field_updates_approved", []),
        "field_updates_blocked": decision_debug.get("field_updates_blocked", []),
        "pending_question": decision_debug.get("pending_question"),
        "pending_confirmation": decision_debug.get("pending_confirmation"),
        "decision_payload": decision_debug.get("decision_payload"),
        "knowledge_pack_version": decision_debug.get("knowledge_pack_version"),
        "repeated_question_blocked": decision_debug.get("repeated_question_blocked", False),
        "protected_field": decision_debug.get("protected_field"),
        "existing_value": decision_debug.get("existing_value"),
        "attempted_question": decision_debug.get("attempted_question"),
        "conflict_detected": decision_debug.get("conflict_detected", False),
        "overwrite_allowed": decision_debug.get("overwrite_allowed"),
        "overwrite_blocked_reason": decision_debug.get("overwrite_blocked_reason"),
        "state_guard_events": decision_debug.get("state_guard_events", []),
        "advisor_decision": decision_debug.get("advisor_decision"),
        "commercial_intent": decision_debug.get("commercial_intent"),
        "pending_to_resume": decision_debug.get("pending_to_resume"),
        "blocked_commercial_actions": decision_debug.get("blocked_commercial_actions", []),
        "quote_gate_evaluated": decision_debug.get("quote_gate_evaluated", False),
        "quote_gate_result": decision_debug.get("quote_gate_result"),
        "quote_gate_blocked_actions": decision_debug.get("quote_gate_blocked_actions", []),
        "quote_ready_fields": decision_debug.get("quote_ready_fields", []),
        "missing_quote_fields": decision_debug.get("missing_quote_fields", []),
        "agent_brain_plan_present": decision_debug.get("agent_brain_plan_present", False),
        "agent_brain_plan_valid": decision_debug.get("agent_brain_plan_valid", False),
        "agent_brain_plan_rejected_reason": decision_debug.get("agent_brain_plan_rejected_reason"),
        "agent_brain_proposed_final_action": decision_debug.get("agent_brain_proposed_final_action"),
        "agent_brain_tool_plan": decision_debug.get("agent_brain_tool_plan", []),
        "agent_brain_proposed_state_updates": decision_debug.get("agent_brain_proposed_state_updates", {}),
        "policy_overrode_agent_brain": decision_debug.get("policy_overrode_agent_brain", False),
        "policy_override_reason": decision_debug.get("policy_override_reason"),
        "detected_intents": decision_debug.get("detected_intents", []),
        "answered_intents": decision_debug.get("answered_intents", []),
        "unresolved_intents": decision_debug.get("unresolved_intents", []),
        "intent_stack": decision_debug.get("intent_stack", []),
        "primary_commercial_goal": decision_debug.get("primary_commercial_goal"),
        "next_required_step": decision_debug.get("next_required_step"),
        "pending_bot_question": decision_debug.get("pending_bot_question"),
        "yes_no_context_resolution": decision_debug.get("yes_no_context_resolution"),
        "resolved_followup_intent": decision_debug.get("resolved_followup_intent"),
        "resolved_followup_entity": decision_debug.get("resolved_followup_entity"),
        "context_resolution_confidence": decision_debug.get("context_resolution_confidence"),
        "soft_close_candidate": decision_debug.get("soft_close_candidate", False),
        "soft_close_blocked_reason": decision_debug.get("soft_close_blocked_reason"),
        "soft_close_applied": decision_debug.get("soft_close_applied", False),
        "model_change_detected": decision_debug.get("model_change_detected", False),
        "alternative_quote_requested": decision_debug.get("alternative_quote_requested", False),
        "previous_model": decision_debug.get("previous_model"),
        "new_model": decision_debug.get("new_model"),
        "selected_catalog_candidate": decision_debug.get("selected_catalog_candidate"),
        "selected_candidate_index": decision_debug.get("selected_candidate_index"),
        "preserved_fields": decision_debug.get("preserved_fields", []),
        "invalidated_fields": decision_debug.get("invalidated_fields", []),
        "recalculated_fields": decision_debug.get("recalculated_fields", []),
        "documents_blocked_until_requote": decision_debug.get(
            "documents_blocked_until_requote", False
        ),
        "quote_count_after_turn": decision_debug.get("quote_count_after_turn"),
    }


def _payload_layer(action_payload: dict[str, Any]) -> dict[str, Any]:
    payload = action_payload if isinstance(action_payload, dict) else {}
    return {
        "action_payload": payload,
        "keys": sorted(str(key) for key in payload.keys()),
        "status": payload.get("status"),
        "has_requirements": "requirements" in payload,
        "has_knowledge": any(
            key in payload for key in ("matches", "results", "retrieved_knowledge")
        ),
    }


def _explanation_layer(
    *,
    pipeline: Any,
    previous_stage: str,
    next_stage: str,
    decision_action: str,
    decision_reason: str,
    flow_mode: FlowMode,
    extracted_data: dict[str, Any],
    pause_bot: bool,
) -> dict[str, Any]:
    summary = _human_summary(
        pipeline=pipeline,
        previous_stage=previous_stage,
        next_stage=next_stage,
        decision_action=decision_action,
        decision_reason=decision_reason,
        flow_mode=flow_mode,
        extracted_data=extracted_data,
        pause_bot=pause_bot,
    )
    return {
        "summary": summary,
        "stage_reason": decision_reason,
        "action_reason": f"acción seleccionada: {decision_action}",
        "flow_mode_reason": f"modo seleccionado: {flow_mode.value}",
    }


def _human_summary(
    *,
    pipeline: Any,
    previous_stage: str,
    next_stage: str,
    decision_action: str,
    decision_reason: str,
    flow_mode: FlowMode,
    extracted_data: dict[str, Any],
    pause_bot: bool,
) -> str:
    to_label = _stage_label(pipeline, next_stage)
    reasons = _human_reasons(extracted_data)
    if previous_stage != next_stage:
        reason_text = ", ".join(reasons) if reasons else f"la decisión fue {decision_reason}"
        return f'El cliente fue movido a "{to_label}" porque {reason_text}.'
    if pause_bot:
        return (
            f'El bot fue pausado porque la decisión "{decision_reason}" '
            "requiere intervención humana."
        )
    if reasons:
        return (
            f'El cliente permanece en "{to_label}" porque '
            f"{', '.join(reasons)}; la acción siguiente es {decision_action}."
        )
    return (
        f'El Runner eligió {decision_action} en modo {flow_mode.value} '
        f'porque la decisión fue "{decision_reason}".'
    )


def _human_reasons(extracted_data: dict[str, Any]) -> list[str]:
    values = {key: _unwrap(value) for key, value in extracted_data.items()}
    reasons: list[str] = []
    for key in sorted(values):
        if len(reasons) >= 3:
            break
        if str(key).lower().startswith(("docs_", "docs.")):
            continue
        if _present(values.get(key)):
            reasons.append(f"{key} asignado")
    return reasons


def _present(value: Any) -> bool:
    return value not in (None, "", [], {})


def _unwrap(value: Any) -> Any:
    if isinstance(value, dict) and "value" in value:
        return value.get("value")
    return value


def _stage_label(pipeline: Any, stage_id: str) -> str:
    for stage in getattr(pipeline, "stages", []) or []:
        if getattr(stage, "id", None) == stage_id:
            return str(getattr(stage, "label", None) or stage_id)
    return stage_id
