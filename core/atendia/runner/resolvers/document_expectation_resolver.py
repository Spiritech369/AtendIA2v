from __future__ import annotations

import re

from atendia.contracts.turn_resolution import Evidence, ResolverAttempt, TurnResolverInput

_ALREADY_SENT_RE = re.compile(
    r"\b(ya\s+te\s+lo\s+mande|ya\s+te\s+lo\s+mand[eé]|ya\s+lo\s+mande|ya\s+lo\s+envie|te\s+lo\s+envie)\b",
    flags=re.IGNORECASE,
)


class DocumentExpectationResolver:
    """Never marks documents by text; it only blocks unsafe state writes."""

    name = "document_expectation_resolver"

    async def resolve(self, input: TurnResolverInput) -> ResolverAttempt | None:
        text = (input.inbound_text or "").strip()
        if not text or _ALREADY_SENT_RE.search(text) is None:
            return None

        summary = _document_summary(input)

        return ResolverAttempt(
            resolver=self.name,
            input=text,
            understood_as="customer_claims_document_was_sent",
            evidence=[
                Evidence(
                    type="document_state",
                    source="conversation_state",
                    value=summary,
                    confidence=1.0,
                )
            ],
            confidence=1.0,
            can_write_state=False,
            requires_confirmation=False,
            suggested_clarification=summary["message"],
            blocked_reason="documents_cannot_be_marked_received_from_text",
        )


def _document_summary(input: TurnResolverInput) -> dict:
    selector_field = getattr(input.pipeline, "document_requirements_field", "selection")
    selector_value = _extract_value(input.extracted_data.get(selector_field))
    if selector_value in (None, "", [], {}):
        return {
            "message": (
                "Lo reviso, pero antes necesito tener definido el tipo de tramite "
                "para saber que documentos aplican."
            ),
            "received": [],
            "missing": [],
            "rejected": [],
            "selector_field": selector_field,
            "selector_value": None,
        }

    requirements = (getattr(input.pipeline, "document_requirements", {}) or {}).get(
        str(selector_value)
    )
    if not requirements:
        return {
            "message": "Lo reviso, pero no tengo requisitos configurados para este caso.",
            "received": [],
            "missing": [],
            "rejected": [],
            "selector_field": selector_field,
            "selector_value": selector_value,
        }

    labels = _document_labels(input)
    received: list[str] = []
    missing: list[str] = []
    rejected: list[str] = []
    for key in requirements:
        label = labels.get(str(key), str(key))
        status = _document_status(input.extracted_data.get(str(key)))
        if status == "ok":
            received.append(label)
        elif status == "rejected":
            rejected.append(label)
        else:
            missing.append(label)

    parts: list[str] = []
    if received:
        parts.append(f"me aparece recibido: {', '.join(received)}")
    if rejected:
        parts.append(f"hay que reenviar: {', '.join(rejected)}")
    if missing:
        parts.append(f"me falta: {', '.join(missing)}")
    if not parts:
        parts.append("me aparecen completos los documentos de este tramite")

    return {
        "message": "Revise el expediente: " + "; ".join(parts) + ".",
        "received": received,
        "missing": missing,
        "rejected": rejected,
        "selector_field": selector_field,
        "selector_value": selector_value,
    }


def _document_labels(input: TurnResolverInput) -> dict[str, str]:
    labels: dict[str, str] = {}
    for spec in getattr(input.pipeline, "documents_catalog", []) or []:
        key = getattr(spec, "key", None)
        label = getattr(spec, "label", None)
        if key and label:
            labels[str(key)] = str(label)
    return labels


def _extract_value(raw):
    if isinstance(raw, dict):
        if "value" in raw:
            return _extract_value(raw.get("value"))
        if "status" in raw:
            return raw.get("status")
    return raw


def _document_status(raw) -> str:
    value = _extract_value(raw)
    status = str(value or "missing").strip().casefold()
    if status in {"ok", "received", "aprobado", "aprobada"}:
        return "ok"
    if status in {"rejected", "reject", "rechazado", "rechazada"}:
        return "rejected"
    return "missing"
