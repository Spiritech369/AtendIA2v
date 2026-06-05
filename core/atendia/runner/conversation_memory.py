from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any


def build_conversation_summary(
    *,
    previous_summary: str | None,
    extracted_data: dict[str, Any],
    action: str,
    action_payload: dict[str, Any],
    decision_payload: dict[str, Any],
    handoff_triggered: bool = False,
    max_chars: int = 900,
) -> str | None:
    """Refresh the long-lived operational memory for a conversation.

    The summary is intentionally deterministic and fact-based. It should
    describe the customer's useful operational context, not preserve raw chat
    transcript text.
    """

    state = _flat_values(extracted_data)
    previous = _split_sentences(previous_summary)
    dynamic = _dynamic_sentences(state, action_payload)
    events = _event_sentences(
        action=action,
        action_payload=action_payload,
        decision_payload=decision_payload,
        handoff_triggered=handoff_triggered,
    )

    replaced_prefixes = {
        "Cliente busca ",
        "Plan/enganche seleccionado:",
        "Documentos requeridos:",
        "Documentos recibidos:",
        "Documentos faltantes:",
        "Documentos por reenviar:",
    }
    replaced_prefixes.update(_event_prefix(sentence) for sentence in events)
    carried = [
        sentence
        for sentence in previous
        if not any(sentence.startswith(prefix) for prefix in replaced_prefixes if prefix)
    ]

    sentences = _dedupe([*dynamic, *carried, *events])
    if not sentences:
        return None
    return _trim_summary(" ".join(sentences), max_chars=max_chars)


def _dynamic_sentences(
    state: dict[str, Any],
    action_payload: dict[str, Any],
) -> list[str]:
    sentences: list[str] = []
    product = _first_text(
        state,
        "MOTO",
        "modelo_moto",
        "producto_interes",
        "producto",
        "selected_product",
    )
    credit = _first_text(
        state,
        "CREDITO",
        "tipo_credito",
        "credito",
        "selection",
    )
    plan = _first_text(
        state,
        "ENGANCHE",
        "plan_credito",
        "plan",
        "selected_plan",
    )

    if product and credit:
        sentences.append(f"Cliente busca credito {credit} para {product}.")
    elif product:
        sentences.append(f"Cliente esta interesado en {product}.")
    elif credit:
        sentences.append(f"Cliente busca credito {credit}.")
    if plan:
        sentences.append(f"Plan/enganche seleccionado: {plan}.")

    requirements = action_payload.get("requirements")
    if isinstance(requirements, dict):
        required = _doc_labels(requirements.get("required"))
        received = _doc_labels(requirements.get("received"))
        missing = _doc_labels(requirements.get("missing"))
        rejected = _doc_labels(requirements.get("rejected"))
        if required:
            sentences.append(f"Documentos requeridos: {_join(required)}.")
        if received:
            sentences.append(f"Documentos recibidos: {_join(received)}.")
        if missing:
            sentences.append(f"Documentos faltantes: {_join(missing)}.")
        if rejected:
            sentences.append(f"Documentos por reenviar: {_join(rejected)}.")

    return sentences


def _event_sentences(
    *,
    action: str,
    action_payload: dict[str, Any],
    decision_payload: dict[str, Any],
    handoff_triggered: bool,
) -> list[str]:
    sentences: list[str] = []
    if action == "quote" and action_payload.get("status") == "ok":
        quote_sentence = _quote_sentence(action_payload)
        if quote_sentence:
            sentences.append(quote_sentence)

    if action == "lookup_faq" and action_payload.get("status") == "ok":
        topic = _clean_text(action_payload.get("topic")) or "general"
        answer = _clean_text(action_payload.get("answer"))
        if answer:
            sentences.append(f"FAQ respondida ({topic}): {_shorten(answer, 180).rstrip('.')}.")
        else:
            sentences.append(f"FAQ respondida ({topic}).")

    if decision_payload.get("decision") == "protected_field_conflict":
        field = _clean_text(decision_payload.get("field_updated")) or "campo protegido"
        value = _clean_text(decision_payload.get("value"))
        if value:
            sentences.append(f"Conflicto pendiente: confirmar cambio de {field} a {value}.")
        else:
            sentences.append(f"Conflicto pendiente: confirmar cambio de {field}.")

    if handoff_triggered:
        sentences.append("Handoff humano requerido.")

    return sentences


def _quote_sentence(payload: dict[str, Any]) -> str | None:
    name = _clean_text(payload.get("name") or payload.get("sku"))
    if not name:
        return None
    plan = _clean_text(payload.get("requested_plan_code"))
    cash_price = _money(payload.get("cash_price_mxn") or payload.get("list_price_mxn"))
    payment_options = payload.get("payment_options")
    selected_plan = None
    if isinstance(payment_options, dict):
        if plan and isinstance(payment_options.get(plan), dict):
            selected_plan = payment_options.get(plan)
        else:
            selected_plan = next(
                (value for value in payment_options.values() if isinstance(value, dict)),
                None,
            )

    parts = [f"Ultima cotizacion: {name}"]
    if plan:
        parts.append(f"plan {plan}")
    if cash_price:
        parts.append(f"contado {cash_price}")
    if isinstance(selected_plan, dict):
        down_payment = _money(selected_plan.get("down_payment_mxn"))
        installment = _money(selected_plan.get("installment_mxn"))
        term = _clean_text(selected_plan.get("term_count"))
        if down_payment:
            parts.append(f"enganche {down_payment}")
        if installment:
            parts.append(f"pago {installment}")
        if term:
            parts.append(f"plazo {term} quincenas")
    return "; ".join(parts) + "."


def _event_prefix(sentence: str) -> str:
    if sentence.startswith("FAQ respondida ("):
        return sentence.split(":", 1)[0] + ":"
    if sentence.startswith("Ultima cotizacion:"):
        return "Ultima cotizacion:"
    if sentence.startswith("Conflicto pendiente:"):
        return "Conflicto pendiente:"
    if sentence.startswith("Handoff humano requerido."):
        return "Handoff humano requerido."
    return ""


def _flat_values(raw: dict[str, Any]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for key, value in raw.items():
        if not isinstance(key, str):
            continue
        values[key] = _unwrap_value(value)
    return values


def _unwrap_value(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="python")
    if isinstance(value, dict) and "value" in value and "status" not in value:
        return _unwrap_value(value.get("value"))
    return value


def _first_text(values: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        text = _clean_text(values.get(key))
        if text:
            return text
    return None


def _doc_labels(raw_docs: Any) -> list[str]:
    docs = raw_docs if isinstance(raw_docs, list) else []
    labels: list[str] = []
    for doc in docs:
        if not isinstance(doc, dict):
            continue
        label = _clean_text(doc.get("label") or doc.get("key"))
        if label:
            labels.append(label)
    return labels


def _split_sentences(summary: str | None) -> list[str]:
    if not summary:
        return []
    parts = [part.strip() for part in str(summary).replace("\n", " ").split(".")]
    return [part + "." for part in parts if part]


def _dedupe(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        clean = _clean_sentence(value)
        if not clean:
            continue
        key = clean.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(clean)
    return out


def _clean_sentence(value: str) -> str:
    text = " ".join(str(value or "").split())
    if not text:
        return ""
    return text if text.endswith(".") else text + "."


def _clean_text(value: Any) -> str | None:
    if value in (None, "", [], {}):
        return None
    if isinstance(value, dict):
        if "value" in value:
            return _clean_text(value.get("value"))
        return None
    text = " ".join(str(value).split())
    return text or None


def _shorten(value: str, max_chars: int) -> str:
    text = " ".join(value.split())
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "..."


def _join(values: list[str]) -> str:
    return ", ".join(values)


def _money(value: Any) -> str | None:
    if value in (None, ""):
        return None
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return f"${amount:,.0f}"


def _trim_summary(summary: str, *, max_chars: int) -> str:
    text = " ".join(summary.split())
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars].rsplit(". ", 1)[0].strip()
    if not cut:
        cut = text[: max_chars - 1].rstrip()
    return cut if cut.endswith(".") else cut + "."


__all__ = ["build_conversation_summary"]
