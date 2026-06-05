from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

PLACEHOLDER_PATTERNS = (
    "$X",
    "$Y",
    "$Z",
    "{precio}",
    "{enganche}",
    "{pago}",
    "{modelo}",
    "N quincenas",
    "TBD",
    "placeholder",
)


@dataclass
class GateResult:
    passed: bool
    issues: list[str] = field(default_factory=list)


class QuoteConsistencyValidator:
    def validate(
        self,
        *,
        final_message: str,
        fields: dict[str, Any],
        citations: list[dict[str, Any]] | None = None,
    ) -> GateResult:
        issues: list[str] = []
        quote = _dict_value(fields.get("Ultima_Cotizacion"))
        sent = _truthy(fields.get("Cotizacion_Enviada"))
        plan = _text(fields.get("Plan_Credito"))
        enganche_plan = _text(fields.get("Plan_Enganche"))
        moto_field = _text(fields.get("Moto"))
        final = final_message or ""
        folded = _fold(final)
        if any(token in final or _fold(token) in folded for token in PLACEHOLDER_PATTERNS):
            issues.append("quote_placeholder_leak")
        if sent and not quote:
            issues.append("quote_sent_without_snapshot")
            return GateResult(False, sorted(set(issues)))
        if not quote:
            return GateResult(not issues, sorted(set(issues)))
        if quote.get("quote_sent") is False:
            return GateResult(not issues, sorted(set(issues)))

        status = _text(quote.get("status"))
        if sent and status and status != "ok":
            issues.append("quote_sent_snapshot_not_ok")
        quote_moto = _text(quote.get("moto"))
        if sent and not _has_quote_citation(quote, citations or []):
            issues.append("quote_sent_without_quote_source_citation")
        if quote_moto:
            if moto_field and not _same_model(moto_field, quote_moto):
                issues.append("quote_moto_field_mismatch")
            mentioned_models = _mentioned_models(final)
            if mentioned_models and not any(
                _same_model(model, quote_moto) for model in mentioned_models
            ):
                issues.append("quote_final_message_moto_mismatch")
        price = _int_or_none(quote.get("precio_contado_mxn"))
        if price is not None and _contains_price(final) and price not in _money_values(final):
            issues.append("quote_price_mismatch")
        down = _int_or_none(quote.get("enganche_mxn"))
        if down is not None and "enganche" in folded and down not in _money_values(final):
            issues.append("quote_enganche_mismatch")
        payment = _int_or_none(quote.get("pago_quincenal_mxn"))
        if (
            payment is not None
            and any(term in folded for term in ("pagos de", "pago quincenal", "quincenal"))
            and payment not in _money_values(final)
        ):
            issues.append("quote_pago_quincenal_mismatch")
        terms = _int_or_none(quote.get("numero_quincenas"))
        if terms is not None and "quincena" in folded and terms not in _plain_numbers(final):
            issues.append("quote_numero_quincenas_mismatch")

        credit_quote = sent and plan and plan != "Contado"
        if credit_quote and not _text(quote.get("plan_credito")):
            issues.append("quote_credit_plan_missing")
        if credit_quote and not _text(quote.get("plan_enganche")):
            issues.append("quote_credit_enganche_missing")
        if plan == "Contado":
            if _text(quote.get("plan_credito")) != "Contado":
                issues.append("quote_contado_plan_mismatch")
            if _text(quote.get("plan_enganche")) != "100%":
                issues.append("quote_contado_enganche_mismatch")
            if _asks_credit_docs(final):
                issues.append("quote_contado_asks_credit_docs")
        if (
            plan
            and _text(quote.get("plan_credito"))
            and _fold(_text(quote.get("plan_credito"))) != _fold(plan)
        ):
            issues.append("quote_plan_state_mismatch")
        quote_enganche = _text(quote.get("plan_enganche"))
        if enganche_plan and quote_enganche and _fold(quote_enganche) != _fold(enganche_plan):
            issues.append("quote_enganche_state_mismatch")
        return GateResult(not issues, sorted(set(issues)))


class CopyStateConsistencyValidator:
    def validate(
        self,
        *,
        final_message: str,
        fields: dict[str, Any],
        attachments: list[str] | None = None,
    ) -> GateResult:
        final = final_message or ""
        folded = _fold(final)
        plan = _text(fields.get("Plan_Credito"))
        enganche = _text(fields.get("Plan_Enganche"))
        issues: list[str] = []
        plan_mentions = {
            "Nomina Recibos": ("nomina recibos",),
            "Nomina Tarjeta": ("nomina tarjeta", "deposito a tarjeta", "deposito en tarjeta"),
            "Sin Comprobantes": ("sin comprobantes",),
            "Guardia": ("guardia",),
            "Contado": ("plan contado", "comprar de contado", "pagar de contado"),
        }
        for mentioned_plan, terms in plan_mentions.items():
            if any(term in folded for term in terms) and plan and plan != mentioned_plan:
                issues.append("copy_plan_state_mismatch")
        percent_match = re.findall(r"\b(10|15|20|30|100)\s*%", folded)
        for percent in percent_match:
            if enganche and f"{percent}%" != enganche:
                issues.append("copy_enganche_state_mismatch")
        if plan == "Contado" and _asks_credit_docs(final):
            issues.append("copy_contado_asks_credit_docs")
        if any(
            term in folded
            for term in (
                "te aprueban",
                "aprobacion segura",
                "aprobado seguro",
                "seguro te aprueban",
            )
        ):
            issues.append("copy_approval_promise")
        if not attachments and any(
            term in folded
            for term in (
                "recibi tus documentos",
                "recibimos tus documentos",
                "ya tengo tus documentos",
                "documentos recibidos",
            )
        ):
            issues.append("copy_claims_docs_without_attachment")
        if plan and plan != "Contado" and _asks_docs_for_other_plan(final, plan):
            issues.append("copy_docs_for_different_plan")
        return GateResult(not issues, sorted(set(issues)))


class UiConsistencyValidator:
    def validate_fields(self, fields: list[dict[str, Any]]) -> GateResult:
        issues: list[str] = []
        debug_keys = {"simulation_run_id", "simulation_case_id", "initial_fields", "is_simulation"}
        for item in fields:
            key = str(item.get("key") or "")
            group = str(item.get("group") or "")
            render_mode = str(item.get("render_mode") or "")
            if key in debug_keys:
                if group != "debug" or not item.get("is_debug"):
                    issues.append(f"ui_debug_field_group:{key}")
            if key in {"Docs_Checklist", "Ultima_Cotizacion"}:
                if item.get("render_payload") in (None, ""):
                    issues.append(f"ui_missing_render_payload:{key}")
                if render_mode == "text":
                    issues.append(f"ui_raw_json_render_mode:{key}")
                if group != "tecnicos":
                    issues.append(f"ui_technical_field_group:{key}")
            if (
                key in {"simulation_run_id", "simulation_case_id", "initial_fields"}
                and group == "datos_comerciales"
            ):
                issues.append(f"ui_debug_in_commercial:{key}")
        return GateResult(not issues, sorted(set(issues)))


def render_quote_message(quote: dict[str, Any], *, current_message: str = "") -> str:
    moto = _text(quote.get("moto")) or "la moto"
    plan = _text(quote.get("plan_credito"))
    price = _money(_int_or_none(quote.get("precio_contado_mxn")))
    if plan == "Contado":
        return (
            f"La {moto} de contado queda en {price}. "
            "Si quieres, te paso con un asesor para confirmar disponibilidad y forma de pago."
        )
    down = _money(_int_or_none(quote.get("enganche_mxn")))
    payment = _money(_int_or_none(quote.get("pago_quincenal_mxn")))
    terms = _int_or_none(quote.get("numero_quincenas"))
    plan_text = f" con {plan}" if plan else ""
    if down and payment and terms:
        return (
            f"La {moto}{plan_text} queda en precio de contado {price}. "
            f"Enganche {down}, pagos de {payment} por {terms} quincenas."
        )
    if down:
        return (
            f"La {moto}{plan_text} queda en precio de contado {price}. "
            f"Enganche {down}. Un asesor te confirma disponibilidad y pagos exactos."
        )
    if current_message.strip():
        return current_message
    return f"La {moto} queda en precio de contado {price}."


def _asks_credit_docs(text: str) -> bool:
    folded = _fold(text)
    doc_terms = ("document", "ine", "comprobante", "estado de cuenta", "nomina", "recibo")
    if not any(term in folded for term in doc_terms):
        return False
    flow_terms = ("credito", "financ", "papeleria", "requisito", "apartar", "avanzar")
    return any(term in folded for term in flow_terms)


def _asks_docs_for_other_plan(text: str, plan: str) -> bool:
    folded = _fold(text)
    if plan != "Nomina Tarjeta" and "estado de cuenta" in folded:
        return True
    if plan != "Guardia" and "carta de trabajo" in folded:
        return True
    return False


def _has_quote_citation(quote: dict[str, Any], citations: list[dict[str, Any]]) -> bool:
    citation = _dict_value(quote.get("citation"))
    if citation:
        return True
    return any(
        _dict_value(item).get("metadata", {}).get("content_type") == "catalog"
        for item in citations
    )


def _mentioned_models(text: str) -> set[str]:
    folded = _fold(text)
    models: set[str] = set()
    for term, canonical in {
        "r4": "R4",
        "comando": "Comando",
        "adventure": "Adventure",
        "u5": "U5",
    }.items():
        if re.search(rf"\b{re.escape(term)}\b", folded):
            models.add(canonical)
    return models


def _same_model(left: str, right: str) -> bool:
    left_folded = _fold(left)
    right_folded = _fold(right)
    if not left_folded or not right_folded:
        return False
    if left_folded == right_folded:
        return True
    return left_folded in right_folded or right_folded in left_folded


def _contains_price(text: str) -> bool:
    return bool(re.search(r"\$\s*\d", text))


def _money_values(text: str) -> set[int]:
    values: set[int] = set()
    for match in re.finditer(r"\$\s*([0-9][0-9,\.]*)", text):
        raw = re.sub(r"\D", "", match.group(1))
        if raw:
            values.add(int(raw))
    return values


def _plain_numbers(text: str) -> set[int]:
    return {int(match.group(1)) for match in re.finditer(r"\b(\d{1,4})\b", text)}


def _money(value: int | None) -> str:
    if value is None:
        return "$0"
    return f"${value:,}"


def _dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _int_or_none(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(str(value).replace(",", "")))
    except ValueError:
        return None


def _text(value: Any) -> str:
    return str(value or "").strip()


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return _fold(str(value)) in {"true", "si", "sí", "yes", "1"}


def _fold(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(text or ""))
    ascii_text = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return ascii_text.casefold()
