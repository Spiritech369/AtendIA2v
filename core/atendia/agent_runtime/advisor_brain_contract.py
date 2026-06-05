from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from atendia.agent_runtime.canonical import (
    CanonicalProductReference,
    coerce_canonical_product_ref,
)
from atendia.agent_runtime.conversation_progress import latest_customer_act
from atendia.agent_runtime.quote_safety import find_price_mentions
from atendia.agent_runtime.schemas import (
    AdvisorBrainDecision,
    AdvisorBrainStateChange,
    AdvisorBrainToolRequest,
    TurnContext,
)

ALLOWED_ADVISOR_TOOL_NAMES = {
    "catalog.lookup",
    "quote.resolve",
    "requirements.resolve",
    "faq.resolve",
    "handoff.create",
}
QUOTE_STATE_FIELD_ALIASES = {"Ultima_Cotizacion", "Cotizacion_Enviada"}
_PRICE_CONTENT_RE = re.compile(
    r"(?:cash_price|\$|\b(?:precio|cotizaci[oó]n|enganche|mensualidad|mensualidades|"
    r"pagos?|cuotas?|contado|efectivo)\b.{0,24}\d)",
    re.IGNORECASE,
)
_QUOTE_INTENT_RE = re.compile(
    r"\b(?:precio|cot[ií]za(?:me(?:la)?)?|cotizaci[oó]n|cu[aá]nto|cuanto|"
    r"sale|cuesta|queda|contado|efectivo|enganche|mensualidad|pagos?|cuotas?)\b",
    re.IGNORECASE,
)
_DOCUMENT_INTENT_RE = re.compile(
    r"\b(?:documentos?|requisitos?|papeles?|que necesito|qu[eé] ocupo)\b",
    re.IGNORECASE,
)
_PLAN_ALIASES = {
    "cash": "cash",
    "contado": "cash",
    "efectivo": "cash",
    "nomina tarjeta": "Nomina Tarjeta",
    "nómina tarjeta": "Nomina Tarjeta",
    "tarjeta": "Nomina Tarjeta",
    "nomina recibos": "Nomina Recibos",
    "nómina recibos": "Nomina Recibos",
    "sin comprobantes": "Sin Comprobantes",
    "por fuera": "Sin Comprobantes",
}


@dataclass(frozen=True)
class AdvisorBrainContractResult:
    decision: AdvisorBrainDecision
    violations: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)


class AdvisorBrainContractValidator:
    """Deterministic boundary for GPT-authored AdvisorBrain decisions."""

    def normalize(
        self,
        *,
        context: TurnContext,
        decision: AdvisorBrainDecision,
    ) -> AdvisorBrainContractResult:
        violations: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        tools = _normalize_tools(context, decision.required_tools, violations)
        changes = _normalize_state_changes(context, decision.proposed_state_changes, violations)
        response_plan = _sanitize_response_plan(decision.response_plan, warnings)
        progress = _normalize_progress_fields(context, decision, warnings)
        if progress["new_information_detected"] and not _has_explicit_document_intent(
            context.inbound_text
        ):
            tools = [
                tool for tool in tools
                if not _drop_requirements_for_qualification(tool, warnings)
            ]
            response_plan = (
                "Confirmar el dato nuevo del cliente y avanzar sin repetir requisitos, "
                "cotizacion ni preguntas ya contestadas."
            )
        risk_flags = list(decision.risk_flags)
        if violations and "advisor_contract_violation" not in risk_flags:
            risk_flags.append("advisor_contract_violation")
        if warnings and "advisor_contract_warning" not in risk_flags:
            risk_flags.append("advisor_contract_warning")
        metadata = {
            **decision.metadata,
            "advisor_contract": {
                "violations": violations,
                "warnings": warnings,
            },
        }
        normalized = decision.model_copy(
            update={
                "required_tools": tools,
                "proposed_state_changes": changes,
                "response_plan": response_plan,
                "risk_flags": risk_flags,
                **progress,
                "metadata": metadata,
            }
        )
        return AdvisorBrainContractResult(
            decision=normalized,
            violations=violations,
            warnings=warnings,
        )


def advisor_brain_contract_system_rules() -> str:
    return "\n".join(
        [
            "Eres AdvisorBrain para un agente comercial. Tu trabajo es decidir acciones "
            "y herramientas, no redactar la respuesta final al cliente.",
            "",
            "Reglas criticas:",
            "",
            "1. No eres fuente de precios.",
            "2. Nunca inventes precio, enganche, mensualidad, plazo, descuento ni "
            "disponibilidad.",
            "3. Para cotizar, debes solicitar `quote.resolve`.",
            "4. `quote.resolve` requiere producto canonico. Si no tienes producto "
            "canonico, solicita `catalog.lookup`.",
            "5. No uses precios de memoria, texto previo, known_facts incompletos o "
            "ejemplos.",
            "6. No marques `Cotizacion_Enviada`.",
            "7. No escribas `Ultima_Cotizacion`.",
            "8. Si el cliente cambia de producto, no reutilices la cotizacion anterior.",
            "9. Si el cliente pregunta documentos, usa `requirements.resolve`; no "
            "metas precio.",
            "10. Si el cliente pide humano, activa handoff y no intentes cerrar venta.",
            "11. Si el cliente da un dato de calificacion, guardalo con evidencia y "
            "avanza sin repetir preguntas.",
            "",
            "Debes responder exclusivamente JSON valido con este schema:",
            "",
            "{",
            '  "understanding": string,',
            '  "customer_goal": string | null,',
            '  "conversation_goals": string[],',
            '  "known_facts": object,',
            '  "missing_facts": string[],',
            '  "next_best_action": string,',
            '  "required_tools": [',
            "    {",
            '      "name": string,',
            '      "payload": object,',
            '      "reason": string,',
            '      "evidence": string[],',
            '      "required": boolean,',
            '      "metadata": object',
            "    }",
            "  ],",
            '  "proposed_state_changes": [',
            "    {",
            '      "target": string,',
            '      "key": string,',
            '      "value": any,',
            '      "reason": string,',
            '      "evidence": string[],',
            '      "confidence": number,',
            '      "metadata": object',
            "    }",
            "  ],",
            '  "response_plan": string,',
            '  "confidence": number,',
            '  "needs_human": boolean,',
            '  "risk_flags": string[],',
            '  "latest_customer_act": string,',
            '  "new_information_detected": boolean,',
            '  "answered_slot": string | null,',
            '  "should_ask_question": boolean,',
            '  "question_slot": string | null,',
            '  "conversation_progress_action": string,',
            '  "metadata": object',
            "}",
            "",
            "Reglas para productos:",
            "- Producto canonico significa objeto con product_id, sku y display_name.",
            '- Alias como "Adventure", "R4", "U5", "Comando" debe resolverse con '
            "catalog.lookup si aun no esta canonico.",
            '- Selecciones ordinales como "la primera", "esa", "la de arriba" solo '
            "son validas si existe last_options en contexto.",
            "",
            "Reglas para planes:",
            '- "contado", "efectivo", "cash" => plan_code "cash"',
            '- "sin comprobantes", "me pagan por fuera", "sin recibos" => plan_code '
            '"Sin Comprobantes"',
            '- "nomina", "me depositan en tarjeta", "recibos de nomina" => plan_code '
            '"Nomina Tarjeta", si ese plan existe en catalogo',
            "- Si el plan no esta claro, puedes pedir aclaracion o elegir plan por "
            "politica del negocio solo si esta configurada.",
            "",
            "Reglas de progreso conversacional:",
            "- No pongas en missing_facts datos ya conocidos.",
            "- No preguntes Ingreso si el cliente ya dijo como recibe ingresos.",
            "- No preguntes Antiguedad_Laboral si ya la dio.",
            "- No preguntes Producto si ya hay Producto canonico.",
            '- Si el cliente confirma "si", "ok" o "va", avanza al siguiente paso '
            "sin repetir la respuesta previa.",
            "- Si el cliente solo da un dato de calificacion como ingreso, forma "
            "de pago o antiguedad laboral, no pongas requirements.resolve como "
            "next_best_action y no solicites documentos en ese turno.",
            "- Para datos de calificacion usa latest_customer_act "
            "qualification_income o qualification_seniority, "
            "new_information_detected=true y conversation_progress_action "
            "acknowledge_new_information.",
            "- Solo usa requirements.resolve cuando el cliente pide documentos, "
            "requisitos o papeles de forma explicita.",
            "",
            "Ejemplos:",
            "",
            'Cliente: "Quiero la R4, cuanto seria?"',
            "Respuesta esperada:",
            "- catalog.lookup si R4 no esta canonico",
            "- quote.resolve solo despues de tener canonical_product_ref",
            "- response_plan sin precios",
            "",
            'Cliente: "Que documentos necesito?"',
            "Respuesta esperada:",
            "- requirements.resolve",
            "- no quote.resolve salvo que el sistema exija plan",
            "- no precio",
            "",
            'Cliente: "La primera"',
            "Contexto: last_options[0] = Adventure Elite 150 CC",
            "Respuesta esperada:",
            "- proposed_state_changes Producto = canonical_product_ref de last_options[0]",
            "- no precio si el cliente no pidio precio",
            "",
            'Cliente: "Cotizamela"',
            "Contexto: Producto canonico Adventure Elite 150 CC",
            "Respuesta esperada:",
            "- quote.resolve con ese producto",
            "- no texto de precio en response_plan",
            "",
            'Cliente: "Ahora mejor la R4"',
            "Contexto: Ultima_Cotizacion = Adventure Elite 150 CC",
            "Respuesta esperada:",
            "- catalog.lookup R4",
            "- invalidar uso de cotizacion anterior para precio",
            "- no reutilizar precio anterior",
        ]
    )


def advisor_brain_decision_json_schema() -> dict[str, Any]:
    return {
        "name": "advisor_brain_decision",
        "strict": False,
        "schema": {
            "type": "object",
            "properties": {
                "understanding": {"type": "string"},
                "customer_goal": {"type": ["string", "null"]},
                "conversation_goals": {"type": "array", "items": {"type": "string"}},
                "known_facts": {"type": "object"},
                "missing_facts": {"type": "array", "items": {"type": "string"}},
                "next_best_action": {"type": "string"},
                "required_tools": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "enum": sorted(ALLOWED_ADVISOR_TOOL_NAMES),
                            },
                            "payload": {"type": "object"},
                            "reason": {"type": "string"},
                            "evidence": {"type": "array", "items": {"type": "string"}},
                            "required": {"type": "boolean"},
                            "metadata": {"type": "object"},
                        },
                        "required": [
                            "name",
                            "payload",
                            "reason",
                            "evidence",
                            "required",
                            "metadata",
                        ],
                        "additionalProperties": False,
                    },
                },
                "proposed_state_changes": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "target": {"type": "string", "enum": ["contact_field", "lifecycle"]},
                            "key": {"type": "string"},
                            "value": {},
                            "reason": {"type": "string"},
                            "evidence": {"type": "array", "items": {"type": "string"}},
                            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                            "metadata": {"type": "object"},
                        },
                        "required": [
                            "target",
                            "key",
                            "value",
                            "reason",
                            "evidence",
                            "confidence",
                            "metadata",
                        ],
                        "additionalProperties": False,
                    },
                },
                "response_plan": {"type": "string"},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "needs_human": {"type": "boolean"},
                "risk_flags": {"type": "array", "items": {"type": "string"}},
                "latest_customer_act": {"type": "string"},
                "new_information_detected": {"type": "boolean"},
                "answered_slot": {"type": ["string", "null"]},
                "should_ask_question": {"type": "boolean"},
                "question_slot": {"type": ["string", "null"]},
                "conversation_progress_action": {"type": "string"},
                "metadata": {"type": "object"},
            },
            "required": [
                "understanding",
                "customer_goal",
                "conversation_goals",
                "known_facts",
                "missing_facts",
                "next_best_action",
                "required_tools",
                "proposed_state_changes",
                "response_plan",
                "confidence",
                "needs_human",
                "risk_flags",
                "latest_customer_act",
                "new_information_detected",
                "answered_slot",
                "should_ask_question",
                "question_slot",
                "conversation_progress_action",
                "metadata",
            ],
            "additionalProperties": False,
        },
    }


def _normalize_tools(
    context: TurnContext,
    tools: list[AdvisorBrainToolRequest],
    violations: list[dict[str, Any]],
) -> list[AdvisorBrainToolRequest]:
    normalized: list[AdvisorBrainToolRequest] = []
    seen_quote: AdvisorBrainToolRequest | None = None
    for tool in tools:
        if tool.name == "handoff.request":
            tool = tool.model_copy(update={"name": "handoff.create"})
        if tool.name not in ALLOWED_ADVISOR_TOOL_NAMES:
            violations.append({"code": "unsupported_tool", "tool_name": tool.name})
            continue
        if tool.name != "quote.resolve":
            normalized.append(tool)
            continue
        quote_tool = _normalize_quote_tool(context, tool, violations)
        if quote_tool is None:
            continue
        if seen_quote is None:
            seen_quote = quote_tool
            normalized.append(quote_tool)
            continue
        if _quote_tools_compatible(seen_quote, quote_tool):
            violations.append({"code": "duplicate_quote_resolve_dropped", "tool_name": tool.name})
            continue
        violations.append(
            {
                "code": "duplicate_incompatible_quote_resolve",
                "kept_plan_code": seen_quote.payload.get("plan_code"),
                "dropped_plan_code": quote_tool.payload.get("plan_code"),
            }
        )
    return normalized


def _normalize_quote_tool(
    context: TurnContext,
    tool: AdvisorBrainToolRequest,
    violations: list[dict[str, Any]],
) -> AdvisorBrainToolRequest | None:
    if _asks_documents_without_quote(context):
        violations.append({"code": "quote_resolve_not_allowed_for_documents_only"})
        return None
    if not _message_allows_quote_resolve(context):
        violations.append({"code": "quote_resolve_without_quote_intent"})
        return None
    payload = dict(tool.payload)
    product = coerce_canonical_product_ref(payload.get("product"))
    if product is None:
        product = _current_product_ref(context)
        if product is not None:
            violations.append({"code": "quote_resolve_missing_product_normalized_from_state"})
    if product is None:
        alias = (
            payload.get("product")
            or payload.get("query")
            or _alias_from_customer_message(context)
        )
        if alias:
            violations.append(
                {"code": "quote_resolve_without_canonical_product", "alias": str(alias)}
            )
            return AdvisorBrainToolRequest(
                name="catalog.lookup",
                payload={"query": str(alias)},
                reason="Quote requested before canonical product was resolved.",
                evidence=list(tool.evidence) or [context.inbound_text],
                required=True,
                metadata={"advisor_contract_violation": True},
            )
        violations.append({"code": "quote_resolve_without_canonical_product"})
        return None
    payload["product"] = product.model_dump(mode="json")
    payload["plan_code"] = (
        _normalize_plan_code(payload.get("plan_code")) or _current_plan(context) or "cash"
    )
    return tool.model_copy(update={"payload": payload})


def _normalize_state_changes(
    context: TurnContext,
    changes: list[AdvisorBrainStateChange],
    violations: list[dict[str, Any]],
) -> list[AdvisorBrainStateChange]:
    normalized: list[AdvisorBrainStateChange] = []
    product_field = _configured_single_field(context, "product")
    last_quote_field = _configured_single_field(context, "last_quote")
    quote_sent_field = _configured_single_field(context, "quote_sent")
    quote_fields = {last_quote_field, quote_sent_field, *QUOTE_STATE_FIELD_ALIASES}
    for change in changes:
        if change.target not in {"contact_field", "lifecycle"}:
            violations.append({"code": "unsupported_state_target", "target": change.target})
            continue
        if change.target == "contact_field" and change.key in quote_fields:
            violations.append({"code": "forbidden_quote_state_write", "key": change.key})
            continue
        if change.target == "contact_field" and product_field and change.key == product_field:
            product = coerce_canonical_product_ref(change.value)
            if product is None:
                violations.append(
                    {"code": "product_state_requires_canonical_ref", "key": change.key}
                )
                continue
            change = change.model_copy(update={"value": product.model_dump(mode="json")})
        normalized.append(change)
    return normalized


def _sanitize_response_plan(plan: str, warnings: list[dict[str, Any]]) -> str:
    sanitized = str(plan or "")
    mentions = find_price_mentions(sanitized)
    if mentions or _PRICE_CONTENT_RE.search(sanitized):
        for mention in reversed(mentions):
            sanitized = f"{sanitized[:mention.start]}[dato de cotizacion]{sanitized[mention.end:]}"
        sanitized = _PRICE_CONTENT_RE.sub("[dato de cotizacion]", sanitized)
        warnings.append({"code": "response_plan_price_content_removed"})
    return sanitized.strip() or "Responder usando solo herramientas y datos validados."


def _normalize_progress_fields(
    context: TurnContext,
    decision: AdvisorBrainDecision,
    warnings: list[dict[str, Any]],
) -> dict[str, Any]:
    latest_act = latest_customer_act(context.inbound_text)
    answered_slot = _answered_slot_for_latest_act(latest_act)
    new_information = latest_act in {"qualification_income", "qualification_seniority"}
    should_ask = bool(decision.should_ask_question and decision.question_slot)
    question_slot = decision.question_slot
    known_slots = set(context.memory.salient_facts)
    if question_slot in known_slots:
        should_ask = False
        warnings.append({"code": "question_slot_already_known_removed", "slot": question_slot})
    return {
        "latest_customer_act": latest_act,
        "new_information_detected": new_information,
        "answered_slot": answered_slot or decision.answered_slot,
        "should_ask_question": should_ask,
        "question_slot": question_slot if should_ask else None,
        "conversation_progress_action": _progress_action_for_latest_act(latest_act),
    }


def _answered_slot_for_latest_act(latest_act: str | None) -> str | None:
    if latest_act == "qualification_income":
        return "Ingreso"
    if latest_act == "qualification_seniority":
        return "Antiguedad_Laboral"
    return None


def _progress_action_for_latest_act(latest_act: str | None) -> str:
    if latest_act in {"qualification_income", "qualification_seniority"}:
        return "acknowledge_new_information"
    if latest_act == "documents_question":
        return "answer_documents_request"
    if latest_act == "quote_request":
        return "answer_quote_request_with_validated_quote_or_specific_block"
    if latest_act == "handoff_request":
        return "confirm_handoff"
    return "respond_to_latest_customer_act"


def _drop_requirements_for_qualification(
    tool: AdvisorBrainToolRequest,
    warnings: list[dict[str, Any]],
) -> bool:
    if tool.name != "requirements.resolve":
        return False
    warnings.append({"code": "requirements_tool_removed_for_qualification_fact"})
    return True


def _has_explicit_document_intent(text: str | None) -> bool:
    return bool(_DOCUMENT_INTENT_RE.search(str(text or "")))


def _quote_tools_compatible(
    first: AdvisorBrainToolRequest,
    second: AdvisorBrainToolRequest,
) -> bool:
    first_product = coerce_canonical_product_ref(first.payload.get("product"))
    second_product = coerce_canonical_product_ref(second.payload.get("product"))
    return bool(
        first_product
        and second_product
        and first_product.product_id == second_product.product_id
        and str(first.payload.get("plan_code") or "") == str(second.payload.get("plan_code") or "")
    )


def _current_product_ref(context: TurnContext) -> CanonicalProductReference | None:
    product_field = _configured_single_field(context, "product")
    values = [
        context.memory.salient_facts.get(product_field or ""),
        context.memory.salient_facts.get("canonical_product_ref"),
        context.memory.salient_facts.get("Producto"),
    ]
    for value in values:
        product = coerce_canonical_product_ref(value)
        if product is not None:
            return product
    return None


def _current_plan(context: TurnContext) -> str | None:
    for key in ("Plan_Credito", "plan_code", "Plan"):
        value = context.memory.salient_facts.get(key)
        plan = _normalize_plan_code(value)
        if plan:
            return plan
    return None


def _normalize_plan_code(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return _PLAN_ALIASES.get(text.casefold(), text)


def _alias_from_customer_message(context: TurnContext) -> str | None:
    text = str(context.inbound_text or "").strip()
    if not text:
        return None
    if text.casefold() in {"la primera", "primera", "esa", "la otra", "cotizamela", "cotízamela"}:
        return None
    return text[:80]


def _asks_documents_without_quote(context: TurnContext) -> bool:
    text = str(context.inbound_text or "")
    return bool(_DOCUMENT_INTENT_RE.search(text)) and not bool(_QUOTE_INTENT_RE.search(text))


def _message_allows_quote_resolve(context: TurnContext) -> bool:
    return bool(_QUOTE_INTENT_RE.search(str(context.inbound_text or "")))


def _configured_single_field(context: TurnContext, name: str) -> str | None:
    rules = context.tenant_config.ruleset
    fields = _dict(_dict(rules.get("operational_state")).get("fields"))
    value = fields.get(name)
    return str(value) if value else None


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


__all__ = [
    "ALLOWED_ADVISOR_TOOL_NAMES",
    "AdvisorBrainContractResult",
    "AdvisorBrainContractValidator",
    "advisor_brain_contract_system_rules",
    "advisor_brain_decision_json_schema",
]
