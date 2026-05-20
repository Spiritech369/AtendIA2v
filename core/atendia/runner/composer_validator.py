from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

from pydantic import BaseModel, Field

from atendia.contracts.flow_mode import FlowMode
from atendia.runner.composer_protocol import ComposerInput, ComposerOutput


class ComposerValidationIssue(BaseModel):
    code: str
    severity: str = Field(pattern="^(warning|blocking)$")
    message: str
    evidence: str | None = None


class ComposerValidationResult(BaseModel):
    policy_passed: bool
    used_action_payload: bool
    invented_data: bool
    followed_mode: bool
    needs_handoff: bool
    issues: list[ComposerValidationIssue] = Field(default_factory=list)


_MONEY_RE = re.compile(
    r"(?:\$|mxn\s*)\s*(\d{1,3}(?:[,\s]\d{3})*(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)",
    re.I,
)
_APPROVAL_RE = re.compile(
    r"\b("
    r"aprobaci[oó]n\s+(?:segura|garantizada)"
    r"|te\s+(?:aprueban|aprobamos|autorizan)\b"
    r"|cr[eé]dito\s+(?:aprobado|garantizado)"
    r"|100%\s+(?:aprobado|autorizado|seguro)"
    r")\b",
    re.I,
)
_MODEL_ASK_RE = re.compile(
    r"\b(modelo|versi[oó]n|producto|moto)\b.*\b(exacto|interesa|buscas|quieres)\b",
    re.I,
)
_DOC_ASK_RE = re.compile(
    r"\b(?:manda|env[ií]a|comparte|sube|necesito|pido|pedirte)\b.{0,40}"
    r"\b(?P<doc>ine|identificaci[oó]n|comprobante(?:\s+de\s+(?:domicilio|ingresos))?"
    r"|recibo(?:\s+de\s+n[oó]mina)?|estado\s+de\s+cuenta|licencia|curp|rfc|foto)\b",
    re.I,
)


def validate_composer_output(
    *,
    input: ComposerInput,
    output: ComposerOutput,
) -> ComposerValidationResult:
    """Validate Composer text before it reaches Outbox.

    Composer is allowed to be merely imperfect, but not unsafe. The
    score records quality signals; `policy_passed` only fails for issues
    that should stop delivery.
    """

    text = "\n".join(output.messages)
    payload = input.action_payload if isinstance(input.action_payload, dict) else {}
    issues: list[ComposerValidationIssue] = []

    _check_max_length(input, output, issues)
    _check_forbidden_phrases(input, text, issues)
    _check_approval_promises(text, issues)
    _check_invented_prices(payload, text, issues)
    _check_documents_outside_payload(payload, text, issues)

    invented_data = any(
        issue.code in {"invented_price", "document_outside_pipeline"} for issue in issues
    )
    used_action_payload = _uses_action_payload(input, output)
    followed_mode = _followed_mode(input, output, invented_data=invented_data)
    if not followed_mode:
        issues.append(
            ComposerValidationIssue(
                code="mode_not_followed",
                severity="warning",
                message="La respuesta no sigue completamente las reglas del modo.",
            )
        )
    if not used_action_payload and payload:
        issues.append(
            ComposerValidationIssue(
                code="payload_not_used",
                severity="warning",
                message="La respuesta no parece usar datos disponibles del action_payload.",
            )
        )

    blocking = [issue for issue in issues if issue.severity == "blocking"]
    return ComposerValidationResult(
        policy_passed=len(blocking) == 0,
        used_action_payload=used_action_payload,
        invented_data=invented_data,
        followed_mode=followed_mode,
        needs_handoff=len(blocking) > 0,
        issues=issues,
    )


def _check_max_length(
    input: ComposerInput, output: ComposerOutput, issues: list[ComposerValidationIssue]
) -> None:
    max_words = getattr(input.tone, "max_words_per_message", None)
    if not isinstance(max_words, int) or max_words <= 0:
        max_words = 80
    for idx, message in enumerate(output.messages, start=1):
        words = re.findall(r"\S+", message)
        if len(words) > max_words:
            issues.append(
                ComposerValidationIssue(
                    code="max_length_exceeded",
                    severity="blocking",
                    message=f"El mensaje {idx} excede el máximo de {max_words} palabras.",
                    evidence=message[:160],
                )
            )


def _check_forbidden_phrases(
    input: ComposerInput, text: str, issues: list[ComposerValidationIssue]
) -> None:
    phrases: list[str] = []
    raw_phrases = getattr(input.tone, "forbidden_phrases", None)
    if isinstance(raw_phrases, list):
        phrases.extend(str(item) for item in raw_phrases if str(item).strip())
    for guardrail in input.guardrails:
        if "frase prohibida:" in guardrail.lower():
            phrases.append(guardrail.split(":", 1)[1].strip())
    normalized = text.casefold()
    for phrase in phrases:
        if phrase.casefold() in normalized:
            issues.append(
                ComposerValidationIssue(
                    code="forbidden_phrase",
                    severity="blocking",
                    message="La respuesta usa una frase prohibida.",
                    evidence=phrase,
                )
            )


def _check_approval_promises(text: str, issues: list[ComposerValidationIssue]) -> None:
    match = _APPROVAL_RE.search(text)
    if match:
        issues.append(
            ComposerValidationIssue(
                code="approval_promise",
                severity="blocking",
                message="La respuesta promete aprobación o autorización.",
                evidence=match.group(0),
            )
        )


def _check_invented_prices(
    payload: dict[str, Any], text: str, issues: list[ComposerValidationIssue]
) -> None:
    mentioned = {_normalize_money(match.group(1)) for match in _MONEY_RE.finditer(text)}
    mentioned.discard(None)
    if not mentioned:
        return
    allowed = _payload_money_values(payload)
    for amount in sorted(mentioned):
        if amount not in allowed:
            issues.append(
                ComposerValidationIssue(
                    code="invented_price",
                    severity="blocking",
                    message="La respuesta menciona un monto que no está en los datos verificados.",
                    evidence=str(amount),
                )
            )


def _check_documents_outside_payload(
    payload: dict[str, Any], text: str, issues: list[ComposerValidationIssue]
) -> None:
    mentioned = {match.group("doc").casefold() for match in _DOC_ASK_RE.finditer(text)}
    if not mentioned:
        return
    allowed = _payload_document_tokens(payload)
    if not allowed:
        for doc in sorted(mentioned):
            issues.append(
                ComposerValidationIssue(
                    code="document_outside_pipeline",
                    severity="blocking",
                    message="La respuesta pide documentos sin respaldo del pipeline.",
                    evidence=doc,
                )
            )
        return
    for doc in sorted(mentioned):
        if not any(doc in token or token in doc for token in allowed):
            issues.append(
                ComposerValidationIssue(
                    code="document_outside_pipeline",
                    severity="blocking",
                    message="La respuesta pide un documento que no aparece en el pipeline.",
                    evidence=doc,
                )
            )


def _uses_action_payload(input: ComposerInput, output: ComposerOutput) -> bool:
    payload = input.action_payload if isinstance(input.action_payload, dict) else {}
    if not payload:
        return False
    text = "\n".join(output.messages).casefold()
    if payload.get("status") == "no_data":
        missing = payload.get("missing")
        if isinstance(missing, list):
            return bool(_MODEL_ASK_RE.search(text)) or any(
                str(item).replace("_", " ").casefold() in text for item in missing
            )
        return bool(_MODEL_ASK_RE.search(text) or "falta" in text)
    values = _payload_scalar_strings(payload)
    return any(value in text for value in values if len(value) >= 3)


def _followed_mode(input: ComposerInput, output: ComposerOutput, *, invented_data: bool) -> bool:
    payload = input.action_payload if isinstance(input.action_payload, dict) else {}
    text = "\n".join(output.messages).casefold()
    if input.flow_mode == FlowMode.SALES:
        if payload.get("status") == "ok":
            return not invented_data and bool(
                _payload_money_values(payload) or _uses_action_payload(input, output)
            )
        if payload.get("status") == "no_data":
            return not _MONEY_RE.search(text) and bool(
                _MODEL_ASK_RE.search(text) or "modelo" in text
            )
    return not invented_data


def _payload_money_values(payload: dict[str, Any]) -> set[Decimal]:
    values: set[Decimal] = set()
    for key, value in _walk(payload):
        key_text = str(key).casefold()
        money_keys = ("price", "precio", "enganche", "pago", "monto", "amount", "quincenal")
        if any(token in key_text for token in money_keys):
            normalized = _normalize_money(value)
            if normalized is not None:
                values.add(normalized)
    return values


def _payload_document_tokens(payload: dict[str, Any]) -> set[str]:
    tokens: set[str] = set()
    for key, value in _walk(payload):
        key_text = str(key).casefold()
        value_text = str(value).casefold()
        if any(token in key_text for token in ("doc", "requirement", "requisito", "faltante")):
            tokens.update(re.findall(r"[a-záéíóúñ]{3,}(?:\s+[a-záéíóúñ]{3,})?", value_text, re.I))
    return {token.strip() for token in tokens if token.strip()}


def _payload_scalar_strings(payload: dict[str, Any]) -> set[str]:
    values: set[str] = set()
    for _key, value in _walk(payload):
        if isinstance(value, str):
            values.add(value.casefold())
        elif isinstance(value, (int, float, Decimal)):
            values.add(str(value).casefold())
            money = _normalize_money(value)
            if money is not None:
                values.add(_money_without_trailing_zero(money))
    return values


def _walk(value: Any, key: str = "") -> list[tuple[str, Any]]:
    if isinstance(value, dict):
        result: list[tuple[str, Any]] = []
        for child_key, child_value in value.items():
            result.extend(_walk(child_value, str(child_key)))
        return result
    if isinstance(value, list):
        result = []
        for item in value:
            result.extend(_walk(item, key))
        return result
    return [(key, value)]


def _normalize_money(value: Any) -> Decimal | None:
    if isinstance(value, bool):
        return None
    raw = str(value).replace("$", "").replace(",", "").replace(" ", "").strip()
    if not raw:
        return None
    try:
        return Decimal(raw).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None


def _money_without_trailing_zero(value: Decimal) -> str:
    if value == value.to_integral():
        return str(value.quantize(Decimal("1")))
    return str(value.normalize())
