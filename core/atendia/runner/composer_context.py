from __future__ import annotations

from copy import deepcopy
from typing import Any

from atendia.runner.composer_protocol import ComposerContextPack


def build_composer_context_pack(
    *,
    user_message: str,
    recent_history: list[tuple[str, str]],
    extracted_data: dict[str, Any],
    action: str,
    action_payload: dict[str, Any],
    decision_payload: dict[str, Any],
    guardrails: list[str],
    conversation_summary: str | None = None,
) -> ComposerContextPack:
    """Build the explicit "what matters this turn" pack for the Composer."""

    pending_to_resume = _pending_to_resume(action_payload, decision_payload)
    current_questions = _current_questions(user_message)
    return ComposerContextPack(
        user_message=user_message,
        recent_history=_render_recent_history(recent_history),
        conversation_summary=_clean_optional_text(conversation_summary),
        state_facts=_state_facts(extracted_data, action_payload),
        business_facts=_business_facts(action=action, action_payload=action_payload),
        tool_payload=deepcopy(action_payload),
        runner_decision=deepcopy(decision_payload),
        must_answer_first=_must_answer_first(
            user_message=user_message,
            action=action,
            action_payload=action_payload,
            decision_payload=decision_payload,
        ),
        current_questions=current_questions,
        required_answer_targets=[
            str(item.get("target") or "").strip()
            for item in current_questions
            if str(item.get("target") or "").strip()
        ],
        unresolved_intents=list(action_payload.get("unresolved_intents") or []),
        pending_to_resume=pending_to_resume,
        must_not_say=_must_not_say(
            extracted_data=extracted_data,
            action=action,
            action_payload=action_payload,
            guardrails=guardrails,
        ),
    )


def _render_recent_history(history: list[tuple[str, str]]) -> list[str]:
    rendered: list[str] = []
    for role, text in history[-8:]:
        cleaned = str(text or "").strip()
        if cleaned:
            rendered.append(f"{role}: {cleaned}")
    return rendered


def _state_facts(
    extracted_data: dict[str, Any],
    action_payload: dict[str, Any],
) -> dict[str, Any]:
    label_map = {
        "MOTO": "modelo_actual",
        "CREDITO": "plan_actual",
        "ENGANCHE": "enganche",
        "FILTRO": "cumple_antiguedad",
        "ANTIGUEDAD_LABORAL": "antiguedad_laboral",
        "PLAN": "plan_actual",
    }
    facts = {
        label_map.get(str(key).upper(), str(key).lower()): _unwrap_value(value)
        for key, value in extracted_data.items()
    }
    requirements = action_payload.get("requirements")
    if isinstance(requirements, dict):
        facts["documentos_requeridos"] = _doc_labels(requirements.get("required"))
        facts["documentos_recibidos"] = _doc_labels(requirements.get("received"))
        facts["documentos_rechazados"] = _doc_labels(requirements.get("rejected"))
        facts["documentos_faltantes"] = _doc_labels(requirements.get("missing"))
        facts["documentos_completos"] = bool(requirements.get("complete"))
        if requirements.get("selection_key"):
            facts["selector_requisitos"] = requirements.get("selection_key")
    return {key: value for key, value in facts.items() if value not in (None, "", [])}


def _business_facts(*, action: str, action_payload: dict[str, Any]) -> dict[str, Any]:
    facts: dict[str, Any] = {}
    if action == "lookup_faq" and action_payload.get("status") == "ok":
        facts["faq_topic"] = action_payload.get("topic")
        facts["faq_answer"] = action_payload.get("answer")
        facts["faq_answers"] = action_payload.get("answers")
        facts["faq_source"] = action_payload.get("source")
    if action == "quote" and action_payload.get("status") == "ok":
        facts["quote"] = {
            "sku": action_payload.get("sku"),
            "name": action_payload.get("name"),
            "cash_price_mxn": action_payload.get("cash_price_mxn"),
            "list_price_mxn": action_payload.get("list_price_mxn"),
            "requested_plan_code": action_payload.get("requested_plan_code"),
            "payment_options": action_payload.get("payment_options"),
            "requirements": action_payload.get("requirements"),
        }
    if action == "search_catalog" and action_payload.get("status") == "ok":
        facts["catalog"] = {
            "request_type": action_payload.get("request_type"),
            "browse_intent": action_payload.get("browse_intent"),
            "query": action_payload.get("query"),
            "total_results": action_payload.get("total_results"),
            "results": action_payload.get("results"),
            "catalog_url": action_payload.get("catalog_url"),
        }
    requirements = action_payload.get("requirements")
    if isinstance(requirements, dict):
        facts["requirements"] = requirements
    return {key: value for key, value in facts.items() if value not in (None, "", [], {})}


def _must_answer_first(
    *,
    user_message: str,
    action: str,
    action_payload: dict[str, Any],
    decision_payload: dict[str, Any],
) -> str | None:
    suggested = decision_payload.get("suggested_clarification")
    if isinstance(suggested, str) and suggested.strip():
        return suggested.strip()
    if action == "lookup_faq" and action_payload.get("status") == "ok":
        answers = action_payload.get("answers") if isinstance(action_payload.get("answers"), list) else []
        if len(answers) > 1:
            topics = ", ".join(
                str(item.get("topic") or "").strip()
                for item in answers
                if isinstance(item, dict) and str(item.get("topic") or "").strip()
            )
            return f"Responder primero las dudas directas del cliente sobre {topics}."
        topic = str(action_payload.get("topic") or "la duda del cliente").strip()
        return f"Responder primero la duda directa del cliente sobre {topic}."
    if action == "quote" and action_payload.get("status") == "ok":
        return "Presentar primero la cotizacion aprobada del payload."
    if action == "search_catalog" and action_payload.get("status") == "ok":
        return "Mostrar primero las opciones de catalogo solicitadas."
    if decision_payload.get("field_updated"):
        return "Confirmar primero el dato entendido por el Runner."
    if user_message.strip():
        return "Responder primero el mensaje actual del cliente."
    return None


def _pending_to_resume(
    action_payload: dict[str, Any],
    decision_payload: dict[str, Any],
) -> dict[str, Any] | None:
    pending = decision_payload.get("resume_pending_action") or action_payload.get(
        "resume_pending_action"
    )
    if isinstance(pending, dict) and pending:
        return deepcopy(pending)
    requirements = action_payload.get("requirements")
    if isinstance(requirements, dict) and requirements.get("missing"):
        return {
            "type": "ask_missing_documents",
            "missing": requirements.get("missing"),
        }
    return None


def _current_questions(user_message: str) -> list[dict[str, Any]]:
    normalized = str(user_message or "").strip().casefold()
    if not normalized:
        return []
    targets: list[str] = []
    if any(token in normalized for token in ("?", "que ", "como ", "donde ", "cuando ", "cuanto ", "puedo ", "revisan", "hablar con")):
        targets.append("customer_question")
    if any(token in normalized for token in ("aprob", "seguro")):
        targets.append("approval")
    if any(token in normalized for token in ("document", "papel", "ine", "comprobante", "requisito")):
        targets.append("documents")
    if any(token in normalized for token in ("buro", "buró")):
        targets.append("buro")
    if any(token in normalized for token in ("ubicacion", "ubicación", "donde")):
        targets.append("ubicacion")
    if any(token in normalized for token in ("liquid", "adelant", "penalizacion")):
        targets.append("payoff")
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for target in targets:
        if target in seen:
            continue
        seen.add(target)
        out.append({"target": target, "text": str(user_message or "").strip()})
    return out


def _must_not_say(
    *,
    extracted_data: dict[str, Any],
    action: str,
    action_payload: dict[str, Any],
    guardrails: list[str],
) -> list[str]:
    rules = [
        "No inventes precios, pagos, plazos, aprobacion, disponibilidad ni requisitos.",
        "No cambies next_action ni estado; eso ya lo decidio el Runner.",
        "No digas aprobado, garantizado o autorizado si no esta explicitamente en el payload.",
    ]
    rules.extend(str(item).strip() for item in guardrails if str(item).strip())
    label_map = {
        "MOTO": "MOTO (el modelo)",
        "CREDITO": "CREDITO (el plan)",
        "ENGANCHE": "ENGANCHE (el enganche)",
        "FILTRO": "FILTRO (la antiguedad)",
        "ANTIGUEDAD_LABORAL": "ANTIGUEDAD_LABORAL (la antiguedad laboral)",
    }
    for key, value in sorted(extracted_data.items()):
        unwrapped = _unwrap_value(value)
        if unwrapped not in (None, "", []):
            label = label_map.get(str(key).upper(), str(key).lower())
            rules.append(f"No vuelvas a pedir {label}; ya sabemos que es {unwrapped}.")
    if action == "lookup_faq" and action_payload.get("status") == "ok":
        rules.append("No ignores la duda directa; responde la FAQ antes de retomar pendientes.")
    return _dedupe(rules)


def _doc_labels(raw_docs: Any) -> list[str]:
    docs = raw_docs if isinstance(raw_docs, list) else []
    labels: list[str] = []
    for doc in docs:
        if not isinstance(doc, dict):
            continue
        label = doc.get("label") or doc.get("key")
        if label:
            labels.append(str(label))
    return labels


def _unwrap_value(value: Any) -> Any:
    if isinstance(value, dict) and "value" in value and "status" not in value:
        return value.get("value")
    return value


def _clean_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _dedupe(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out


__all__ = ["build_composer_context_pack"]
