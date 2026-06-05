from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

from atendia.agent_runtime.canonical import QuoteSnapshot, coerce_quote_snapshot
from atendia.agent_runtime.quote_safety import find_price_mentions, visible_quote_signal
from atendia.agent_runtime.schemas import ToolExecutionResult, TurnContext

_QUOTE_INTENT_RE = re.compile(
    r"\b(?:precio|cot[ií]za(?:me(?:la)?)?|cotizaci[oó]n|cu[aá]nto|cuanto|"
    r"sale|cuesta|queda|contado|efectivo|enganche|mensualidad|pagos?|cuotas?)\b",
    re.IGNORECASE,
)
_DOC_INTENT_RE = re.compile(
    r"\b(?:documentos?|requisitos?|papeles?|que necesito|qu[eé] ocupo)\b",
    re.IGNORECASE,
)
_HUMAN_INTENT_RE = re.compile(
    r"\b(?:humano|asesor|persona|francisco|ejecutivo)\b",
    re.IGNORECASE,
)
_SIMPLE_ACK_RE = re.compile(r"^\s*(?:ok|va|si|sí|sale|listo|gracias)\s*[.!?]*\s*$", re.IGNORECASE)
_QUOTE_REPEAT_RE = re.compile(
    r"\b(?:cu[aá]nto era|cuanto era|rep[ií]teme|recuerdame|recu[eé]rdame|"
    r"otra vez|de nuevo)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class QuoteContext:
    can_quote: bool
    quote_snapshot: QuoteSnapshot | None
    quote_snippet: str | None
    blocked_reason: str | None

    def to_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["quote_snapshot"] = (
            self.quote_snapshot.model_dump(mode="json") if self.quote_snapshot else None
        )
        return payload


class QuoteSnippetBuilder:
    """Build customer-visible quote snippets only from validated snapshots."""

    def build(self, snapshot: QuoteSnapshot) -> str:
        return quote_snippet_from_snapshot(snapshot)


def build_quote_context(
    *,
    context: TurnContext,
    tool_results: list[ToolExecutionResult],
) -> QuoteContext:
    text = str(context.inbound_text or "")
    if _asks_human(text):
        return _blocked("human_handoff_requested")
    if _asks_documents(text) and not _has_quote_intent(text):
        return _blocked("documents_without_price_request")
    if _is_simple_ack(text):
        return _blocked("ack_without_quote_repeat_request")

    current_snapshot = _quote_snapshot_from_tool_results(tool_results)
    if current_snapshot is not None:
        snapshot = current_snapshot.with_integrity_hash()
        return QuoteContext(
            can_quote=True,
            quote_snapshot=snapshot,
            quote_snippet=quote_snippet_from_snapshot(snapshot),
            blocked_reason=None,
        )

    if not _has_quote_intent(text) and not _asks_quote_repeat(text):
        return _blocked("no_current_quote_request")

    active_snapshot = _active_quote_snapshot(context)
    if active_snapshot is not None:
        snapshot = active_snapshot.with_integrity_hash()
        return QuoteContext(
            can_quote=True,
            quote_snapshot=snapshot,
            quote_snippet=quote_snippet_from_snapshot(snapshot),
            blocked_reason=None,
        )
    return _blocked("quote_snapshot_required")


def enforce_quote_context_on_message(
    *,
    message: str,
    quote_context: QuoteContext,
    context: TurnContext,
) -> tuple[str, list[str]]:
    notes: list[str] = []
    text = str(message or "").strip()
    if not text:
        text = "Lo reviso y te respondo con datos validados."

    if not quote_context.can_quote:
        if visible_quote_signal(text):
            notes.append("removed_price_without_quote_context")
            text = _fallback_without_price(context, quote_context.blocked_reason)
        return text, notes

    snippet = quote_context.quote_snippet or ""
    if not snippet:
        if visible_quote_signal(text):
            notes.append("removed_price_without_quote_snippet")
            text = _fallback_without_price(context, "quote_snippet_required")
        return text, notes

    if snippet not in text:
        notes.append("quote_snippet_inserted_or_restored")
        text = _compose_with_exact_snippet(context, snippet)
    else:
        text = _remove_prices_outside_snippet(text, snippet, notes)

    if quote_context.quote_snapshot and _message_mentions_other_product(
        text,
        quote_context.quote_snapshot,
    ):
        notes.append("replaced_product_mismatched_quote_copy")
        text = _compose_with_exact_snippet(context, snippet)
    return text, notes


def quote_snippet_from_snapshot(snapshot: QuoteSnapshot) -> str:
    product = snapshot.product.display_name or snapshot.product.sku
    plan = snapshot.plan_name or snapshot.plan_code or "plan validado"
    pricing = snapshot.pricing
    cash_price = _amount(pricing.get("cash_price") or pricing.get("contado"))
    down_payment = _amount(pricing.get("down_payment") or pricing.get("enganche"))
    installment = _amount(
        pricing.get("installment")
        or pricing.get("monthly_payment")
        or pricing.get("payment")
        or pricing.get("mensualidad")
    )
    installments = _amount(
        pricing.get("installments")
        or pricing.get("term")
        or pricing.get("plazo")
        or pricing.get("quincenas")
    )
    period_label = str(
        pricing.get("period_label")
        or pricing.get("payment_period_label")
        or pricing.get("period")
        or "pagos"
    ).strip()
    if cash_price is not None and down_payment is None and installment is None:
        return f"De contado, la {product} queda en ${cash_price:,}."
    if down_payment is not None and installment is not None and installments is not None:
        return (
            f"Para {product} con {plan}, el enganche es de ${down_payment:,} "
            f"y los pagos son de ${installment:,} por {installments} {period_label}."
        )
    if cash_price is not None:
        return f"De contado, la {product} queda en ${cash_price:,}."
    return f"Cotizacion validada para {product} con {plan}."


def _quote_snapshot_from_tool_results(
    tool_results: list[ToolExecutionResult],
) -> QuoteSnapshot | None:
    for result in tool_results:
        if result.tool_name != "quote.resolve" or result.status != "succeeded":
            continue
        snapshot = coerce_quote_snapshot(result.data.get("quote_snapshot"))
        if snapshot is not None:
            return snapshot
    return None


def _active_quote_snapshot(context: TurnContext) -> QuoteSnapshot | None:
    quote_field = _configured_single_field(context, "last_quote")
    return coerce_quote_snapshot(
        context.memory.last_quote_snapshot
        or context.memory.salient_facts.get(quote_field or "")
        or context.memory.salient_facts.get("Ultima_Cotizacion")
    )


def _remove_prices_outside_snippet(message: str, snippet: str, notes: list[str]) -> str:
    start = message.find(snippet)
    if start < 0:
        return message
    end = start + len(snippet)
    before = message[:start]
    after = message[end:]
    if visible_quote_signal(before) or visible_quote_signal(after):
        notes.append("removed_extra_prices_outside_quote_snippet")
        before = _strip_price_mentions(before)
        after = _strip_price_mentions(after)
    return f"{before}{snippet}{after}".strip()


def _strip_price_mentions(text: str) -> str:
    result = text
    for mention in reversed(find_price_mentions(text)):
        result = f"{result[:mention.start]}[dato validado en la cotizacion]{result[mention.end:]}"
    return result


def _compose_with_exact_snippet(context: TurnContext, snippet: str) -> str:
    if _asks_documents(context.inbound_text):
        return (
            "Te comparto la cotizacion validada y tambien reviso los documentos "
            f"segun el plan. {snippet}"
        )
    return f"Perfecto, uso la cotizacion validada del sistema. {snippet}"


def _fallback_without_price(context: TurnContext, blocked_reason: str | None) -> str:
    if _asks_human(context.inbound_text):
        return "Te paso con una persona del equipo para que lo revise directo."
    if _asks_documents(context.inbound_text):
        return (
            "Te digo los documentos con la informacion validada del plan; no recotizo "
            "si no me pediste precio."
        )
    if blocked_reason == "ack_without_quote_repeat_request":
        return (
            "Va, sigo con ese contexto. Dime si quieres que avancemos con documentos "
            "o aclaramos algo."
        )
    return (
        "Para darte precio necesito confirmar la cotizacion del sistema y asi no "
        "pasarte un dato incorrecto."
    )


def _message_mentions_other_product(message: str, snapshot: QuoteSnapshot) -> bool:
    folded = _fold(message)
    own = {
        _fold(snapshot.product.display_name),
        _fold(snapshot.product.sku),
        _fold(snapshot.product.product_id),
    }
    known = {"adventure", "r4", "u5", "comando", "work"}
    return any(token in folded and all(token not in value for value in own) for token in known)


def _has_quote_intent(text: str) -> bool:
    return bool(_QUOTE_INTENT_RE.search(str(text or "")))


def _asks_documents(text: str) -> bool:
    return bool(_DOC_INTENT_RE.search(str(text or "")))


def _asks_human(text: str) -> bool:
    return bool(_HUMAN_INTENT_RE.search(str(text or "")))


def _is_simple_ack(text: str) -> bool:
    return bool(_SIMPLE_ACK_RE.search(str(text or "")))


def _asks_quote_repeat(text: str) -> bool:
    return bool(_QUOTE_REPEAT_RE.search(str(text or "")))


def _blocked(reason: str) -> QuoteContext:
    return QuoteContext(
        can_quote=False,
        quote_snapshot=None,
        quote_snippet=None,
        blocked_reason=reason,
    )


def _amount(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    text = str(value).strip()
    if not text:
        return None
    digits = re.sub(r"[^0-9.]", "", text)
    if not digits:
        return None
    try:
        number = float(digits)
    except ValueError:
        return None
    return int(number) if number.is_integer() else None


def _configured_single_field(context: TurnContext, name: str) -> str | None:
    rules = context.tenant_config.ruleset
    fields = _dict(_dict(rules.get("operational_state")).get("fields"))
    value = fields.get(name)
    return str(value) if value else None


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _fold(value: Any) -> str:
    return str(value or "").casefold()


__all__ = [
    "QuoteContext",
    "QuoteSnippetBuilder",
    "build_quote_context",
    "enforce_quote_context_on_message",
    "quote_snippet_from_snapshot",
]
