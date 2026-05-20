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
        "catalog_available": bool(getattr(pipeline, "docs_per_plan", None)),
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
    if _has_valid_seniority(values):
        reasons.append("ya tiene antigüedad válida")
    if _present(values.get("tipo_credito")):
        reasons.append("tipo_credito asignado")
    if _present(values.get("modelo_interes")) or _present(values.get("interes_producto")):
        reasons.append("modelo_interes detectado")
    return reasons


def _has_valid_seniority(values: dict[str, Any]) -> bool:
    if values.get("cumple_antiguedad") is True:
        return True
    for key in ("tiempo_empleo_meses", "antiguedad_laboral_meses", "antiguedad_empleo_meses"):
        try:
            if values.get(key) is not None and float(values[key]) >= 6:
                return True
        except (TypeError, ValueError):
            continue
    return False


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
