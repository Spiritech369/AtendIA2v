from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass
from typing import Any, Literal

from atendia.agent_runtime.canonical import (
    CanonicalProductReference,
    QuoteSnapshot,
    coerce_canonical_product_ref,
    coerce_quote_snapshot,
    normalize_catalog_token,
)
from atendia.agent_runtime.schemas import FieldUpdate, ToolExecutionResult, TurnContext, TurnOutput
from atendia.config import get_settings

_SAFE_REWRITE_GENERIC = (
    "Para darte el precio exacto necesito confirmar el modelo y el plan con la "
    "cotizacion del sistema. Te lo reviso y te paso el dato correcto."
)
_SAFE_REWRITE_PRODUCT_WITHOUT_SNAPSHOT = (
    "Ya tengo el modelo, pero necesito confirmar la cotizacion del sistema antes "
    "de darte precio para no pasarte un dato incorrecto."
)
_SAFE_REWRITE_MISSING_PRODUCT = (
    "Para cotizarte bien, dime que modelo quieres o elige una de las opciones."
)
_VALID_QUOTE_SOURCES = {
    "quoteresolver",
    "quote resolver",
    "quote_resolver",
    "quote resolve",
    "quote.resolve",
}
_MONEY_NUMBER = r"(?:\d{1,3}(?:[,\s]\d{3})+|\d{4,8}|\d{1,3})"
_SYMBOL_MONEY_RE = re.compile(
    rf"(?<![\w+])\$\s*(?P<number>{_MONEY_NUMBER})(?:\.\d{{1,2}})?(?!\s*(?:cc|%))",
    re.IGNORECASE,
)
_CURRENCY_MONEY_RE = re.compile(
    rf"(?<![\w+])(?P<number>{_MONEY_NUMBER})(?:\.\d{{1,2}})?\s*(?:mxn|m\.?n\.?)\b",
    re.IGNORECASE,
)
_QUOTE_AMOUNT_RE = re.compile(
    rf"\b(?:queda(?:ria)?\s+en|sale\s+en|cuesta|precio(?:\s+en\s+efectivo)?|"
    rf"de\s+contado\s+queda\s+en|contado\s+queda\s+en|enganche(?:\s+de)?|"
    rf"pagos?(?:\s+de)?|mensualidad(?:\s+de)?|cuotas?(?:\s+de)?)"
    rf"\s*(?:de|en)?\s*\$?\s*(?P<number>{_MONEY_NUMBER})(?:\.\d{{1,2}})?(?!\s*(?:cc|%))",
    re.IGNORECASE,
)
_CASH_PHRASE_RE = re.compile(
    r"\b(?:precio\s+en\s+efectivo|de\s+contado\s+queda\s+en)\b",
    re.IGNORECASE,
)
_QUINCENA_RE = re.compile(r"\b(?P<number>\d{1,3})\s+quincenas?\b", re.IGNORECASE)
_MONTH_RE = re.compile(r"\b(?P<number>\d{1,3})\s+mes(?:es)?\b", re.IGNORECASE)
_FINANCE_WORD_RE = re.compile(
    r"\b(?:enganche|mensualidad|mensualidades|pagos?|cuotas?|quincenas?|plazo)\b",
    re.IGNORECASE,
)
_CASH_WORD_RE = re.compile(r"\b(?:contado|efectivo|cash)\b", re.IGNORECASE)
_PRODUCT_BEFORE_QUOTE_RE = re.compile(
    r"\b(?:la|el|modelo|moto)\s+(?P<product>[a-z0-9][a-z0-9-]{1,24})"
    r"(?:\s+[a-z0-9]{1,10})?\s+"
    r"(?:queda|sale|cuesta|cotiza|de\s+contado|enganche|pagos?|mensualidad|precio)\b",
    re.IGNORECASE,
)
_PRODUCT_START_QUOTE_RE = re.compile(
    r"^\s*(?P<product>[a-z0-9][a-z0-9-]{1,24})\s+"
    r"(?:queda|sale|cuesta|cotiza|de\s+contado|enganche|pagos?|mensualidad|precio)\b",
    re.IGNORECASE,
)
_PRODUCT_STOPWORDS = {
    "cotizacion",
    "credito",
    "moto",
    "modelo",
    "precio",
    "plan",
    "contado",
    "efectivo",
}


@dataclass(frozen=True)
class PriceMention:
    text: str
    value: int | None
    kind: str
    start: int
    end: int


@dataclass(frozen=True)
class QuoteSafetyMetrics:
    price_mentions_count: int
    matched_snapshot_amounts: int
    unmatched_amounts: list[str]


@dataclass(frozen=True)
class QuoteSafetyEvaluation:
    allowed: bool
    visible_price_detected: bool
    failures: list[str]
    quote_snapshot_id: str | None
    quote_snapshot_hash: str | None
    sanitized_message: str
    metrics: QuoteSafetyMetrics

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class QuoteSafetyResult:
    output: TurnOutput
    allowed: bool
    visible_price_detected: bool
    failures: list[str]
    quote_snapshot_id: str | None
    quote_snapshot_hash: str | None
    sanitized_message: str
    metrics: QuoteSafetyMetrics
    action: str
    reason: str | None = None

    @property
    def has_visible_quote(self) -> bool:
        return self.visible_price_detected

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.pop("output", None)
        payload["has_visible_quote"] = self.visible_price_detected
        return payload


class QuoteSafetyGuard:
    """Deterministic guard for customer-visible quote and price copy."""

    def __init__(self, mode: Literal["shadow", "block"] | None = None) -> None:
        self._mode = mode

    def evaluate(
        self,
        *,
        context: TurnContext,
        message: str,
        tool_results: list[ToolExecutionResult] | None = None,
        field_updates: list[FieldUpdate] | None = None,
    ) -> QuoteSafetyEvaluation:
        mentions = find_price_mentions(message)
        snapshot, snapshot_source, permission_failures = _quote_permission(
            context=context,
            message=message,
            tool_results=list(tool_results or []),
            field_updates=list(field_updates or []),
        )
        failures = list(permission_failures)
        visible_price_detected = bool(mentions)
        matched_amounts = 0
        unmatched_amounts: list[str] = []

        if visible_price_detected and snapshot is None:
            if not _has_canonical_product(context, field_updates or []):
                failures = _append_unique(failures, "quoted_without_canonical_product")
            failures = _append_unique(failures, "visible_price_without_quote_permission")
        elif visible_price_detected and snapshot is not None:
            amount_failures, matched_amounts, unmatched_amounts = _validate_amounts(
                mentions,
                snapshot,
            )
            failures.extend(amount_failures)
            failures.extend(_validate_product_text(message, snapshot))
            failures.extend(_validate_plan_text(message, snapshot))
            if snapshot_source == "memory":
                failures.extend(
                    _validate_active_quote_reuse(
                        context,
                        message,
                        snapshot,
                        field_updates or [],
                    )
                )

        failures = _dedupe(failures)
        allowed = not visible_price_detected or not failures
        sanitized_message = message if allowed else _fallback_message(context, field_updates or [])
        return QuoteSafetyEvaluation(
            allowed=allowed,
            visible_price_detected=visible_price_detected,
            failures=failures,
            quote_snapshot_id=snapshot.snapshot_id if snapshot and allowed else None,
            quote_snapshot_hash=snapshot.integrity_hash if snapshot and allowed else None,
            sanitized_message=sanitized_message,
            metrics=QuoteSafetyMetrics(
                price_mentions_count=len(mentions),
                matched_snapshot_amounts=matched_amounts,
                unmatched_amounts=unmatched_amounts,
            ),
        )

    def apply(
        self,
        *,
        context: TurnContext,
        output: TurnOutput,
        tool_results: list[ToolExecutionResult] | None = None,
    ) -> QuoteSafetyResult:
        tool_results = list(tool_results or [])
        mode = self._mode or get_settings().quote_safety_guard_mode
        quote_sent_field = _configured_single_field(context, "quote_sent")
        evaluation = self.evaluate(
            context=context,
            message=output.final_message,
            tool_results=tool_results,
            field_updates=output.field_updates,
        )
        snapshot, snapshot_source, _ = _quote_permission(
            context=context,
            message=output.final_message,
            tool_results=tool_results,
            field_updates=output.field_updates,
        )
        trace = dict(output.trace_metadata)

        if evaluation.visible_price_detected and not evaluation.allowed:
            guard_payload = {
                **evaluation.to_dict(),
                "has_visible_quote": evaluation.visible_price_detected,
                "action": "shadow" if mode == "shadow" else "rewritten",
                "mode": mode,
                "reason": evaluation.failures[0] if evaluation.failures else None,
            }
            trace["quote_safety"] = guard_payload
            trace["guard_result"] = guard_payload
            if mode == "shadow":
                shadow_output = output.model_copy(update={"trace_metadata": trace})
                return QuoteSafetyResult(
                    output=shadow_output,
                    allowed=False,
                    visible_price_detected=True,
                    failures=evaluation.failures,
                    quote_snapshot_id=None,
                    quote_snapshot_hash=None,
                    sanitized_message=evaluation.sanitized_message,
                    metrics=evaluation.metrics,
                    action="shadow",
                    reason=evaluation.failures[0] if evaluation.failures else None,
                )
            filtered_updates = _drop_quote_state_updates(
                output.field_updates,
                context=context,
                quote_sent_field=quote_sent_field,
            )
            safe_output = output.model_copy(
                update={
                    "final_message": evaluation.sanitized_message,
                    "field_updates": filtered_updates,
                    "risk_flags": _append_unique(output.risk_flags, "quote_safety_rewritten"),
                    "trace_metadata": trace,
                }
            )
            return QuoteSafetyResult(
                output=safe_output,
                allowed=False,
                visible_price_detected=True,
                failures=evaluation.failures,
                quote_snapshot_id=None,
                quote_snapshot_hash=None,
                sanitized_message=evaluation.sanitized_message,
                metrics=evaluation.metrics,
                action="rewritten",
                reason=evaluation.failures[0] if evaluation.failures else None,
            )

        updates = _drop_model_authored_quote_updates(
            output.field_updates,
            context=context,
            quote_sent_field=quote_sent_field,
        )
        if (
            evaluation.visible_price_detected
            and evaluation.allowed
            and snapshot is not None
            and quote_sent_field
            and snapshot_source == "tool_result"
        ):
            updates = _ensure_quote_sent_update(
                updates,
                context=context,
                quote_sent_field=quote_sent_field,
                snapshot=snapshot,
            )
        guard_payload = {
            **evaluation.to_dict(),
            "has_visible_quote": evaluation.visible_price_detected,
            "action": "allowed",
            "mode": mode,
            "reason": None,
        }
        trace["quote_safety"] = guard_payload
        trace["guard_result"] = guard_payload
        safe_output = output.model_copy(update={"field_updates": updates, "trace_metadata": trace})
        return QuoteSafetyResult(
            output=safe_output,
            allowed=True,
            visible_price_detected=evaluation.visible_price_detected,
            failures=[],
            quote_snapshot_id=evaluation.quote_snapshot_id,
            quote_snapshot_hash=evaluation.quote_snapshot_hash,
            sanitized_message=evaluation.sanitized_message,
            metrics=evaluation.metrics,
            action="allowed",
        )


def visible_quote_signal(message: str | None) -> bool:
    return bool(find_price_mentions(message or ""))


def find_price_mentions(message: str | None) -> list[PriceMention]:
    text = str(message or "")
    if not text.strip():
        return []
    mentions: list[PriceMention] = []
    spans: list[tuple[int, int]] = []

    def add(match: re.Match[str], kind: str, *, value_group: str | None = "number") -> None:
        if any(_overlaps(match.span(), span) for span in spans):
            return
        number = match.group(value_group) if value_group else None
        value = _amount_to_int(number) if number is not None else None
        if value is not None and _looks_like_false_positive_number(
            text,
            match.start(),
            match.end(),
        ):
            return
        spans.append(match.span())
        mentions.append(
            PriceMention(
                text=text[match.start() : match.end()],
                value=value,
                kind=kind,
                start=match.start(),
                end=match.end(),
            )
        )

    for regex, kind in (
        (_SYMBOL_MONEY_RE, "money_symbol"),
        (_CURRENCY_MONEY_RE, "money_currency"),
        (_QUOTE_AMOUNT_RE, "quote_amount"),
    ):
        for match in regex.finditer(text):
            add(match, kind)
    for match in _CASH_PHRASE_RE.finditer(text):
        add(match, "cash_phrase", value_group=None)
    for match in _QUINCENA_RE.finditer(text):
        value = _amount_to_int(match.group("number"))
        if value is not None and 1 <= value <= 180:
            add(match, "installment_count")
    if _has_price_context(text):
        for match in _MONTH_RE.finditer(text):
            value = _amount_to_int(match.group("number"))
            if value is not None and 1 <= value <= 120:
                add(match, "term_months")
    return sorted(mentions, key=lambda mention: mention.start)


def _quote_permission(
    *,
    context: TurnContext,
    message: str,
    tool_results: list[ToolExecutionResult],
    field_updates: list[FieldUpdate],
) -> tuple[QuoteSnapshot | None, str | None, list[str]]:
    failures: list[str] = []
    for result in tool_results:
        if result.tool_name != "quote.resolve" or result.status != "succeeded":
            continue
        snapshot = coerce_quote_snapshot(result.data.get("quote_snapshot"))
        snapshot, snapshot_failures = _validated_snapshot(snapshot, require_integrity=False)
        failures.extend(snapshot_failures)
        if snapshot and _snapshot_matches_current_product(context, snapshot, field_updates):
            return snapshot.with_integrity_hash(), "tool_result", []
        if snapshot:
            failures.append("stale_quote_product_mismatch")

    quote_field = _configured_single_field(context, "last_quote")
    if quote_field and any(
        update.field_key == quote_field and update.value is None
        for update in field_updates
    ):
        return None, None, _dedupe([*failures, "quote_snapshot_invalidated"])

    snapshot = coerce_quote_snapshot(
        context.memory.last_quote_snapshot
        or context.memory.salient_facts.get(quote_field or "")
    )
    snapshot, snapshot_failures = _validated_snapshot(snapshot, require_integrity=True)
    failures.extend(snapshot_failures)
    if snapshot is None:
        return None, None, _dedupe(failures)
    if not _snapshot_matches_current_product(context, snapshot, field_updates):
        return None, None, _dedupe([*failures, "stale_quote_product_mismatch"])
    reuse_failures = _validate_active_quote_reuse(context, message, snapshot, field_updates)
    if reuse_failures:
        return None, None, _dedupe([*failures, *reuse_failures])
    return snapshot.with_integrity_hash(), "memory", _dedupe(failures)


def _validated_snapshot(
    snapshot: QuoteSnapshot | None,
    *,
    require_integrity: bool,
) -> tuple[QuoteSnapshot | None, list[str]]:
    if snapshot is None:
        return None, []
    failures: list[str] = []
    if not snapshot.snapshot_id:
        failures.append("quote_snapshot_missing_id")
    if not snapshot.product.product_id:
        failures.append("quote_snapshot_missing_product_id")
    if not snapshot.product.sku:
        failures.append("quote_snapshot_missing_sku")
    if not snapshot.product.display_name:
        failures.append("quote_snapshot_missing_display_name")
    if not (snapshot.plan_code or snapshot.plan_name):
        failures.append("quote_snapshot_missing_plan")
    if not snapshot.pricing:
        failures.append("quote_snapshot_missing_pricing")
    if not snapshot.currency:
        failures.append("quote_snapshot_missing_currency")
    if _source_token(snapshot.source_tool) not in _VALID_QUOTE_SOURCES:
        failures.append("quote_snapshot_untrusted_source")
    if not snapshot.created_at:
        failures.append("quote_snapshot_missing_created_at")
    if require_integrity and not snapshot.integrity_hash:
        failures.append("quote_snapshot_missing_integrity_hash")
    return (None, failures) if failures else (snapshot, [])


def _validate_amounts(
    mentions: list[PriceMention],
    snapshot: QuoteSnapshot,
) -> tuple[list[str], int, list[str]]:
    snapshot_amounts = _snapshot_amounts(snapshot)
    matched = 0
    unmatched: list[str] = []
    for mention in mentions:
        if mention.value is None:
            continue
        if mention.value in snapshot_amounts:
            matched += 1
        else:
            unmatched.append(mention.text.strip())
    failures = ["quote_amount_not_in_snapshot"] if unmatched else []
    return failures, matched, unmatched


def _validate_product_text(message: str, snapshot: QuoteSnapshot) -> list[str]:
    candidates = _product_mentions_before_quote(message)
    if not candidates:
        return []
    aliases = _snapshot_product_aliases(snapshot.product)
    for candidate in candidates:
        if candidate not in aliases:
            return ["quote_product_mismatch"]
    return []


def _validate_plan_text(message: str, snapshot: QuoteSnapshot) -> list[str]:
    text = _fold(message)
    mentions_cash = bool(_CASH_WORD_RE.search(text))
    mentions_finance = bool(_FINANCE_WORD_RE.search(text))
    pricing = snapshot.pricing
    has_cash = _pricing_has_cash(pricing)
    has_finance = _pricing_has_finance(pricing)
    plan_text = _fold(
        " ".join(str(value or "") for value in (snapshot.plan_code, snapshot.plan_name))
    )

    failures: list[str] = []
    if mentions_cash and not (has_cash or "contado" in plan_text or "cash" in plan_text):
        failures.append("quote_plan_mismatch")
    if mentions_finance and not (has_finance or "credito" in plan_text or "financ" in plan_text):
        failures.append("quote_plan_mismatch")
    if mentions_cash and mentions_finance and not (has_cash and has_finance):
        failures.append("quote_mixed_cash_finance_not_in_snapshot")
    return _dedupe(failures)


def _validate_active_quote_reuse(
    context: TurnContext,
    message: str,
    snapshot: QuoteSnapshot,
    field_updates: list[FieldUpdate],
) -> list[str]:
    failures: list[str] = []
    product_field = _configured_single_field(context, "product")
    for update in field_updates:
        if product_field and update.field_key == product_field:
            product = coerce_canonical_product_ref(update.value)
            if product and product.product_id != snapshot.product.product_id:
                failures.append("stale_quote_product_mismatch")
        if update.metadata.get("quote_snapshot_invalidated"):
            failures.append("quote_snapshot_invalidated")
    candidates = _product_mentions_before_quote(message)
    aliases = _snapshot_product_aliases(snapshot.product)
    if any(candidate not in aliases for candidate in candidates):
        failures.append("stale_quote_product_mismatch")
    return _dedupe(failures)


def _snapshot_matches_current_product(
    context: TurnContext,
    snapshot: QuoteSnapshot,
    field_updates: list[FieldUpdate],
) -> bool:
    product_field = _configured_single_field(context, "product")
    if not product_field:
        return True
    product_value = context.memory.salient_facts.get(product_field)
    for update in field_updates:
        if update.field_key == product_field:
            product_value = update.value
    product = coerce_canonical_product_ref(product_value)
    if product is None:
        return True
    return product.product_id == snapshot.product.product_id


def _drop_quote_state_updates(
    updates: list[FieldUpdate],
    *,
    context: TurnContext,
    quote_sent_field: str | None,
) -> list[FieldUpdate]:
    quote_field = _configured_single_field(context, "last_quote")
    return [
        update
        for update in updates
        if update.field_key not in {quote_field, quote_sent_field}
    ]


def _drop_model_authored_quote_updates(
    updates: list[FieldUpdate],
    *,
    context: TurnContext,
    quote_sent_field: str | None,
) -> list[FieldUpdate]:
    quote_field = _configured_single_field(context, "last_quote")
    filtered: list[FieldUpdate] = []
    for update in updates:
        if update.field_key == quote_field and update.source != "action":
            continue
        if update.field_key == quote_sent_field and update.value is True:
            continue
        filtered.append(update)
    return filtered


def _ensure_quote_sent_update(
    updates: list[FieldUpdate],
    *,
    context: TurnContext,
    quote_sent_field: str,
    snapshot: QuoteSnapshot,
) -> list[FieldUpdate]:
    if any(update.field_key == quote_sent_field and update.value is True for update in updates):
        return updates
    return [
        *updates,
        FieldUpdate(
            field_key=quote_sent_field,
            value=True,
            reason="QuoteSafetyGuard allowed final message with a valid QuoteSnapshot.",
            evidence=list(snapshot.evidence) or [context.inbound_text],
            confidence=1.0,
            source="action",
            metadata={
                "quote_safety_guard": True,
                "quote_snapshot_required": True,
                "quote_snapshot_id": snapshot.snapshot_id,
                "quote_snapshot_hash": snapshot.integrity_hash,
            },
        ),
    ]


def _fallback_message(context: TurnContext, field_updates: list[FieldUpdate]) -> str:
    if not _has_canonical_product(context, field_updates):
        return _SAFE_REWRITE_MISSING_PRODUCT
    if not _has_valid_quote_snapshot_in_context(context):
        return _SAFE_REWRITE_PRODUCT_WITHOUT_SNAPSHOT
    return _SAFE_REWRITE_GENERIC


def _has_canonical_product(context: TurnContext, field_updates: list[FieldUpdate]) -> bool:
    product_field = _configured_single_field(context, "product")
    values: list[Any] = []
    if product_field:
        values.append(context.memory.salient_facts.get(product_field))
    values.extend(
        update.value
        for update in field_updates
        if product_field and update.field_key == product_field
    )
    return any(coerce_canonical_product_ref(value) is not None for value in values)


def _has_valid_quote_snapshot_in_context(context: TurnContext) -> bool:
    quote_field = _configured_single_field(context, "last_quote")
    snapshot = coerce_quote_snapshot(
        context.memory.last_quote_snapshot
        or context.memory.salient_facts.get(quote_field or "")
    )
    snapshot, failures = _validated_snapshot(snapshot, require_integrity=True)
    return snapshot is not None and not failures


def _snapshot_amounts(snapshot: QuoteSnapshot) -> set[int]:
    amounts: set[int] = set()

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for nested in value.values():
                visit(nested)
            return
        if isinstance(value, list):
            for nested in value:
                visit(nested)
            return
        amount = _amount_to_int(value)
        if amount is not None:
            amounts.add(amount)

    visit(snapshot.pricing)
    return amounts


def _product_mentions_before_quote(message: str) -> set[str]:
    folded = _fold(message)
    candidates: set[str] = set()
    for regex in (_PRODUCT_BEFORE_QUOTE_RE, _PRODUCT_START_QUOTE_RE):
        for match in regex.finditer(folded):
            candidate = normalize_catalog_token(match.group("product"))
            if candidate and candidate not in _PRODUCT_STOPWORDS:
                candidates.add(candidate)
    return candidates


def _snapshot_product_aliases(product: CanonicalProductReference) -> set[str]:
    values = {
        product.product_id,
        product.sku,
        product.display_name,
    }
    aliases = {normalize_catalog_token(value) for value in values if value}
    for value in values:
        for token in re.split(r"[^a-zA-Z0-9]+", str(value or "")):
            normalized = normalize_catalog_token(token)
            if normalized and any(char.isalpha() for char in normalized):
                aliases.add(normalized)
    return {alias for alias in aliases if alias}


def _pricing_has_cash(pricing: dict[str, Any]) -> bool:
    return any(
        "cash" in _fold(key) or "contado" in _fold(key) or "efectivo" in _fold(key)
        for key in pricing
    )


def _pricing_has_finance(pricing: dict[str, Any]) -> bool:
    finance_terms = (
        "down",
        "enganche",
        "installment",
        "mensual",
        "pago",
        "cuota",
        "quincena",
        "plazo",
        "term",
    )
    return any(any(term in _fold(key) for term in finance_terms) for key in pricing)


def _has_price_context(text: str) -> bool:
    folded = _fold(text)
    return bool(
        _SYMBOL_MONEY_RE.search(text)
        or _CURRENCY_MONEY_RE.search(text)
        or _QUOTE_AMOUNT_RE.search(text)
        or _FINANCE_WORD_RE.search(folded)
        or _CASH_WORD_RE.search(folded)
    )


def _looks_like_false_positive_number(text: str, start: int, end: int) -> bool:
    before = text[max(0, start - 3) : start]
    after = text[end : min(len(text), end + 6)]
    if re.search(r"^\s*(?:cc|%)\b", after, re.IGNORECASE):
        return True
    if before.endswith("+"):
        return True
    return False


def _amount_to_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    text = str(value).strip()
    if not text:
        return None
    if "%" in text:
        return None
    digits = re.sub(r"[^0-9.]", "", text)
    if not digits:
        return None
    try:
        numeric = float(digits)
    except ValueError:
        return None
    return int(numeric) if numeric.is_integer() else None


def _configured_single_field(context: TurnContext, name: str) -> str | None:
    rules = context.tenant_config.ruleset
    fields = _dict(_dict(rules.get("operational_state")).get("fields"))
    value = fields.get(name)
    return str(value) if value else None


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _source_token(value: str | None) -> str:
    return _fold(value or "").replace("_", " ").strip()


def _fold(value: Any) -> str:
    text = str(value or "").casefold()
    normalized = unicodedata.normalize("NFD", text)
    return "".join(char for char in normalized if unicodedata.category(char) != "Mn")


def _overlaps(first: tuple[int, int], second: tuple[int, int]) -> bool:
    return first[0] < second[1] and second[0] < first[1]


def _append_unique(values: list[str], item: str) -> list[str]:
    return values if item in values else [*values, item]


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result


__all__ = [
    "PriceMention",
    "QuoteSafetyEvaluation",
    "QuoteSafetyGuard",
    "QuoteSafetyMetrics",
    "QuoteSafetyResult",
    "find_price_mentions",
    "visible_quote_signal",
]
