"""Legacy sales decision policy kept for ConversationRunner fallback only.

AgentRuntime v2 tenants must use tenant configuration and TurnOutput rather
than this legacy response-planning layer.
"""

from __future__ import annotations

import re
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.credit_plan_invariants import (
    build_credit_plan_menu,
    enforce_credit_plan_invariants,
)
from atendia.runner.acknowledgement_policy import (
    AcknowledgementPolicyRequest,
    classify_acknowledgement,
)
from atendia.runner.attachment_intent_policy import (
    AttachmentIntentResult,
    classify_attachment_intent,
    document_key_for_attachment_label,
)
from atendia.runner.catalog_reference_policy import catalog_browse_request_type
from atendia.runner.document_language import (
    extract_document_labels_from_text,
    humanize_document_labels,
    infer_requirement_subject,
    join_humanized_documents,
    requirement_subject_answer,
)
from atendia.runner.employment_seniority_policy import (
    ANTIGUEDAD_LABORAL_FIELD_KEY,
    is_valid_seniority_duration,
    parse_employment_seniority,
)
from atendia.runner.explicit_down_payment_policy import (
    ExplicitDownPaymentChange,
    extract_explicit_down_payment_change,
    minimum_plan_code_for_credit,
    quote_payload_has_plan,
    requested_plan_meets_minimum,
)
from atendia.runner.quote_memory_policy import should_recall_last_quote
from atendia.text_normalization import normalize_whatsapp_text
from atendia.tools.base import ToolNoDataResult
from atendia.tools.deterministic import get_missing_documents, list_catalog, resolve_credit_plan
from atendia.tools.lookup_faq import answer_faq_from_pack, answer_faqs_from_pack
from atendia.tools.quote import quote as quote_catalog_plan
from atendia.tools.search_catalog import search_catalog

AdvisorAction = Literal[
    "ask_income_type",
    "resolve_credit_plan",
    "catalog_browse",
    "catalog_filter",
    "resolve_model",
    "quote",
    "quote_memory_recall",
    "answer_faq_and_resume",
    "process_document",
    "ask_missing_document",
    "clarify_ambiguous_yes_no",
    "ask_one_missing_field",
    "soft_close",
    "hold_no_action",
]

_RUNTIME_ACTION_BY_ADVISOR: dict[str, str] = {
    "ask_income_type": "ask_credit_context",
    "resolve_credit_plan": "resolve_credit_plan",
    "catalog_browse": "search_catalog",
    "catalog_filter": "search_catalog",
    "resolve_model": "search_catalog",
    "quote": "quote",
    "quote_memory_recall": "quote",
    "answer_faq_and_resume": "lookup_faq",
    "process_document": "classify_document",
    "ask_missing_document": "classify_document",
    "clarify_ambiguous_yes_no": "ask_clarification",
    "ask_one_missing_field": "ask_field",
    "soft_close": "soft_close",
    "hold_no_action": "ask_clarification",
}

_YES_NO_REPLIES = {
    "si",
    "sí",
    "claro",
    "ok",
    "okay",
    "va",
    "sale",
    "simon",
    "no",
}
_DEICTIC_REPLY_TERMS = {"esa", "ese", "eso", "aquella", "aquel", "misma", "mismo"}
_CREDIT_INTENT_TERMS = {
    "credito",
    "creditos",
    "financiamiento",
    "financiar",
    "pagos",
    "mensualidades",
    "quincenas",
}
_CASH_INTENT_TERMS = {"contado", "cash"}
_GENERIC_CREDIT_VALUES = {"credito", "credit", "moto", "financiamiento", "pagos"}
_GENERIC_MODEL_VALUES = {"moto", "motocicleta", "modelo", "modelos", "opciones"}
_GENERIC_MODEL_MODIFIERS = {
    "otra",
    "otro",
    "otras",
    "otros",
    "diferente",
    "distinta",
    "distinto",
    "mas",
    "nuevo",
    "nueva",
}
_CATALOG_REQUEST_TERMS = {"catalogo", "catalog", "modelos", "opciones", "motos"}
_CATALOG_COLOR_TERMS = {"color", "colores"}
_CATALOG_REQUEST_VERBS = {
    "ver",
    "pasas",
    "pasame",
    "muestras",
    "muestrame",
    "tienes",
    "manejas",
    "dame",
    "mandame",
}
_CATALOG_STYLE_TERMS = {
    "chopper",
    "cuatrimoto",
    "cuatrimotos",
    "deportiva",
    "deportivas",
    "doble",
    "motocarro",
    "motocarros",
    "motoneta",
    "motonetas",
    "naked",
    "scooter",
    "trabajo",
    "urbana",
    "urbanas",
}
_CATALOG_STYLE_PRIORITY = (
    "chopper",
    "cuatrimoto",
    "cuatrimotos",
    "deportiva",
    "deportivas",
    "motocarro",
    "motocarros",
    "trabajo",
    "scooter",
    "motoneta",
    "motonetas",
    "doble",
    "naked",
    "urbana",
    "urbanas",
)
_MODEL_QUERY_STOPWORDS = {
    "a",
    "al",
    "busco",
    "cambio",
    "con",
    "de",
    "del",
    "el",
    "esa",
    "ese",
    "info",
    "informacion",
    "la",
    "las",
    "le",
    "los",
    "me",
    "mejor",
    "modelo",
    "moto",
    "motos",
    "para",
    "prefiero",
    "quiero",
    "no",
    "una",
    "un",
    "ya",
}
_MODEL_CHANGE_QUERY_MARKERS = {
    "actualiza",
    "cambiala",
    "cambiar",
    "cambiarla",
    "cambio",
    "mejor",
    "prefiero",
}
_MODEL_CHANGE_CONTEXT_STOPWORDS = _MODEL_QUERY_STOPWORDS | _MODEL_CHANGE_QUERY_MARKERS | {
    "credito",
    "creditos",
    "igual",
    "lo",
    "por",
    "queda",
}
_QUOTE_REQUEST_TERMS = {
    "cotiza",
    "cotizacion",
    "cotizar",
    "precio",
    "cuesta",
    "sale",
    "mensualidad",
    "mensualidades",
    "quincena",
    "quincenal",
    "pago",
    "pagos",
}
_REQUIREMENTS_QUESTION_TERMS = {
    "papeles",
    "papeleria",
    "requisito",
    "requisitos",
    "documento",
    "documentos",
    "ine",
    "comprobante",
    "falta",
    "faltan",
    "faltaria",
}
_REQUIREMENTS_CONTEXT_PHRASES = (
    "que ocupo",
    "que necesito",
    "como le hago",
    "como sigo",
    "para que los usan",
    "para que usan",
    "porque documentos",
    "por que documentos",
    "estado de cuenta",
    "estados de cuenta",
)
_DOWN_PAYMENT_TERMS = {"enganche", "anticipo", "inicial"}
_CREDIT_HISTORY_TERMS = {"buro", "historial", "deuda", "deudas", "adeudo", "adeudos"}
_TIMING_TERMS = {
    "tiempo",
    "tarda",
    "tardan",
    "tardar",
    "revision",
    "revisan",
    "proceso",
    "procede",
    "proceder",
    "aprobar",
    "aprobacion",
    "respuesta",
}
_LOCATION_TERMS = {"ubicacion", "direccion", "donde", "sucursal"}
_PAYOFF_TERMS = {"liquidar", "liquidacion", "abonar", "abono", "adelantar", "adelanto"}
_SOFT_OFF_TOPIC_TERMS = {
    "jaja",
    "jajaja",
    "jeje",
    "compa",
    "primo",
    "corre",
    "gana",
    "ganar",
    "luego",
}
_DOCUMENT_SUBMISSION_CONFIRMATION_PHRASES = (
    "ahi esta",
    "ahi est",
    "ya quedo",
    "ya mande todo",
    "ya mande",
    "ya te mande lo demas",
    "ya mande lo demas",
    "ya te lo mande",
    "ya te lo envie",
    "ya esta todo",
    "listo",
)
_POST_QUOTE_PROGRESS_PHRASES = (
    "entonces seguimos",
    "seguimos",
    "vamos",
    "dale",
    "me interesa",
    "quiero seguir",
    "quiero avanzar",
    "si seguimos",
)
_POST_QUOTE_PROGRESS_ACK_TERMS = {
    "si",
    "s",
    "va",
    "sale",
    "claro",
    "correcto",
    "adelante",
}
_NEGATIVE_RECEIPTS_PHRASES = (
    "no tengo recibos",
    "no me dan recibos",
    "no tengo nomina",
    "no es nomina",
    "me pagan por fuera",
    "efectivo",
    "no tengo comprobantes",
    "sin comprobante",
    "sin comprobar",
    "no se puede comprobar",
)
_POSITIVE_RECEIPTS_PHRASES = (
    "si tengo recibos",
    "tengo recibos",
    "recibos de nomina",
    "me pagan con recibos",
    "me dan recibos",
    "tengo recibos de nomina",
    "con recibos",
)
_EARLY_MODEL_CHANGE_PHRASES = (
    "mejor cambiala por",
    "cambiala por",
    "mejor la",
    "quiero cambiar a",
    "cambio a",
)
_MODEL_SIGNAL_ARTICLES = {"la", "el", "una", "un"}
_MODEL_SIGNAL_DISALLOWED_TOKENS = {
    "si",
    "no",
    "tengo",
    "recibos",
    "nomina",
    "tarjeta",
    "depositan",
    "deposito",
    "gracias",
    "hola",
    "buenas",
    "credito",
    "ingresos",
    "documentos",
    "papeles",
    "comprobante",
    "ine",
    "enganche",
    "anos",
    "ano",
    "trabajo",
    "empleo",
}


@dataclass
class SalesAdvisorDecisionInput:
    tenant_id: UUID
    inbound_text: str
    attachments: list[Any]
    metadata: Mapping[str, Any]
    nlu: Any
    operational_intent: Any
    extracted_data: dict[str, Any]
    pending_confirmation: str | None
    pipeline: Any
    current_stage: str | None = None
    knowledge_pack: Mapping[str, Any] | None = None
    vision_writes: list[Any] = field(default_factory=list)
    catalog_url: str | None = None
    conversation_summary: str | None = None


class SalesAdvisorDecision(BaseModel):
    commercial_intent: str = "unknown"
    next_action: AdvisorAction = "hold_no_action"
    runtime_action: str = "ask_clarification"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason_codes: list[str] = Field(default_factory=list)
    field_updates_approved: dict[str, Any] = Field(default_factory=dict)
    field_updates_blocked: list[dict[str, Any]] = Field(default_factory=list)
    tool_payload: dict[str, Any] = Field(default_factory=dict)
    pending_to_resume: dict[str, Any] | None = None
    blocked_commercial_actions: list[str] = Field(default_factory=list)
    commercial_state: dict[str, Any] = Field(default_factory=dict)
    faq_tool_used: bool = False
    catalog_category: str | None = None
    catalog_browse_intent: str | None = None
    executed_tools: list[dict[str, Any]] = Field(default_factory=list)
    tool_call_logs: list[dict[str, Any]] = Field(default_factory=list)
    state_consistency_errors: list[dict[str, Any]] = Field(default_factory=list)
    should_override_runtime_action: bool = False


@dataclass(frozen=True)
class AcknowledgementContextResolution:
    advisor_action: AdvisorAction
    runtime_action: str
    commercial_intent: str
    reason: str
    forbidden_actions_applied: list[str]
    payload: dict[str, Any] = field(default_factory=dict)
    pending_to_resume: dict[str, Any] | None = None
    confidence: float = 0.82


@dataclass(frozen=True)
class IncomeDisambiguationSignals:
    income_ambiguity: bool = False
    payroll_ambiguous: bool = False
    deposit_ambiguous: bool = False
    dual_income_detected: bool = False
    needs_income_disambiguation: bool = False
    credit_plan_write_blocked_reason: str | None = None


class SalesAdvisorDecisionPolicy:
    """Commercial policy layer that chooses the sales next action before pipeline questions."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def decide(self, input: SalesAdvisorDecisionInput) -> SalesAdvisorDecision:
        state = _commercial_state(input)
        blocked_updates = _blocked_nlu_updates(input)

        credit_plan_reply = await self._credit_plan_selection_decision(
            input,
            state,
            blocked_updates,
        )
        if credit_plan_reply is not None:
            return credit_plan_reply

        negative_receipts_override = await self._negative_receipts_plan_correction_decision(
            input,
            state,
            blocked_updates,
        )
        if negative_receipts_override is not None:
            return negative_receipts_override

        resolved_plan_needs_model = _resolved_plan_needs_model_decision(
            input,
            state,
            blocked_updates,
        )
        if resolved_plan_needs_model is not None:
            return resolved_plan_needs_model

        seniority_to_income_type = _employment_seniority_to_income_type_decision(
            input,
            state,
            blocked_updates,
        )
        if seniority_to_income_type is not None:
            return seniority_to_income_type

        employment_seniority_decision = _employment_seniority_decision(
            input,
            state,
            blocked_updates,
        )
        if employment_seniority_decision is not None:
            return employment_seniority_decision

        plan_restate_needs_model = self._plan_restate_needs_model_decision(
            input,
            state,
            blocked_updates,
        )
        if plan_restate_needs_model is not None:
            return plan_restate_needs_model

        explicit_down_payment = extract_explicit_down_payment_change(input.inbound_text)
        if explicit_down_payment is not None:
            down_payment_decision = await self._explicit_down_payment_change_decision(
                input,
                state,
                blocked_updates,
                explicit_down_payment,
            )
            if down_payment_decision is not None:
                return down_payment_decision

        documents_submission_decision = _documents_submission_confirmation_decision(
            input,
            state,
            blocked_updates,
        )
        if documents_submission_decision is not None:
            return documents_submission_decision

        text_document_claim_decision = _text_document_claim_without_evidence_decision(
            input,
            state,
            blocked_updates,
        )
        if text_document_claim_decision is not None:
            return text_document_claim_decision

        post_quote_progress_decision = self._post_quote_progress_decision(
            input,
            state,
            blocked_updates,
        )
        if post_quote_progress_decision is not None:
            return post_quote_progress_decision

        complaint_followup_decision = _complaint_policy_followup_decision(
            input,
            state,
            blocked_updates,
        )
        if complaint_followup_decision is not None:
            return complaint_followup_decision

        resolved_model_from_entities = _resolved_model_entity_value(input)
        if (
            resolved_model_from_entities
            and state.get("model")
            and not _is_cash_price_request(input)
            and not _credit_mode_switch_preserves_existing_model(input)
            and _resolved_model_entity_supported_by_text(
                input,
                resolved_model_from_entities,
                existing_model=True,
            )
        ):
            model_changed = (
                _normalize(str(resolved_model_from_entities))
                != _normalize(str(state.get("model") or ""))
            )
            if model_changed:
                next_action: AdvisorAction = "quote" if state.get("plan") else "ask_income_type"
                model_change_source = (
                    "catalog_selection"
                    if _is_catalog_selection_reference(input.inbound_text)
                    else "explicit_model"
                )
                return _decision(
                    input=input,
                    state={**state, "model": resolved_model_from_entities},
                    commercial_intent="model_change",
                    next_action=next_action,
                    confidence=0.95,
                    reasons=["explicit_model_change_takes_priority_over_catalog_browse"],
                    approved_updates={"MOTO": resolved_model_from_entities},
                    blocked_updates=blocked_updates,
                    payload={
                        "status": "ok",
                        "request_type": "resolve_model",
                        "model": resolved_model_from_entities,
                        "model_change_detected": True,
                        "model_change_source": model_change_source,
                        "previous_model": state.get("model"),
                        "new_model": resolved_model_from_entities,
                        "preserved_fields": [
                            field
                            for field, key in (
                                ("CREDITO", "income_type"),
                                ("ENGANCHE", "plan"),
                                ("FILTRO", "seniority_eligible"),
                            )
                            if state.get(key) not in (None, "", [], {})
                        ],
                        "invalidated_fields": ["quote_valid", "last_quote_payload"],
                        "documents_blocked_until_requote": bool(state.get("plan")),
                        "catalog_selected_model": resolved_model_from_entities,
                        "catalog_resolution_status": "resolved_from_entity",
                        "resolved_from_context": True,
                    },
                    blocked_actions=[
                        "explicit_model_before_catalog_browse",
                        "no_ask_documents_before_quote_without_model_plan",
                    ],
                )
            if state.get("plan") and _explicit_quote_request(input):
                return _decision(
                    input=input,
                    state=state,
                    commercial_intent="quote_ready",
                    next_action="quote",
                    confidence=0.86,
                    reasons=["explicit_current_model_quote_request"],
                    blocked_updates=blocked_updates,
                    payload={
                        "status": "ok",
                        "request_type": "quote_refresh",
                        "model": resolved_model_from_entities,
                    },
                    blocked_actions=[
                        "explicit_model_before_catalog_browse",
                        "no_ask_documents_before_quote_without_model_plan",
                    ],
                )

        contextual_catalog_browse_intent = _catalog_browse_intent_from_context(input)
        if contextual_catalog_browse_intent is not None:
            return await self._catalog_decision(
                input,
                state,
                blocked_updates,
                category=_catalog_category(input.inbound_text),
                reasons=["catalog_requested_from_recent_catalog_context"],
                browse_intent=contextual_catalog_browse_intent,
                commercial_intent="catalog_followup",
            )

        contextual_followup = await self._contextual_followup_decision(
            input,
            state,
            blocked_updates,
        )
        if contextual_followup is not None:
            return contextual_followup

        if _deictic_current_quote_request(input.inbound_text) and state.get("model") and state.get("plan"):
            return _decision(
                input=input,
                state=state,
                commercial_intent="quote_ready",
                next_action="quote",
                confidence=0.9,
                reasons=["deictic_quote_request_uses_current_model_and_plan"],
                blocked_updates=blocked_updates,
                payload={
                    "status": "ok",
                    "request_type": "quote_refresh",
                    "model": state.get("model"),
                },
                blocked_actions=[
                    "no_ask_clarification_when_current_quote_context_ready",
                    "no_ask_model_already_resolved",
                ],
            )

        acknowledgement_decision = self._acknowledgement_decision(
            input,
            state,
            blocked_updates,
        )
        if acknowledgement_decision is not None:
            return acknowledgement_decision

        confirmation_decision = _confirmation_resume_decision(input, state, blocked_updates)
        if confirmation_decision is not None:
            return confirmation_decision

        attachment_decision = _non_document_attachment_decision(input, state, blocked_updates)
        if attachment_decision is not None:
            return attachment_decision

        if _document_upload_signal(input):
            return await self._process_document(input, state, blocked_updates)

        if _is_ambiguous_yes_no(input):
            return _decision(
                input=input,
                state=state,
                commercial_intent="ambiguous_yes_no",
                next_action="clarify_ambiguous_yes_no",
                confidence=0.9,
                reasons=["short_yes_no_without_safe_pending_context"],
                blocked_updates=_ambiguous_yes_no_blocked_updates(input, blocked_updates),
                payload={
                    "status": "ok",
                    "request_type": "clarify_ambiguous_yes_no",
                    "suggested_clarification": _ambiguous_yes_no_prompt(input, state),
                },
                blocked_actions=[
                    "no_write_critical_fields_without_clear_pending_question",
                    "no_quote_without_model_and_plan",
                ],
            )

        soft_off_topic = _soft_off_topic_decision(input, state, blocked_updates)
        if soft_off_topic is not None:
            return soft_off_topic

        multi_intent_decision = self._multi_intent_faq_decision(
            input,
            state,
            blocked_updates,
        )
        if multi_intent_decision is not None:
            return multi_intent_decision

        if _is_requirements_question(input):
            return self._requirements_decision(input, state, blocked_updates)

        if _is_catalog_color_question(input):
            return await self._catalog_decision(
                input,
                state,
                blocked_updates,
                category=None,
                reasons=["catalog_color_question_requested"],
            )

        faq_payload = answer_faq_from_pack(
            question=input.inbound_text,
            knowledge_pack=input.knowledge_pack,
            allow_tag_only_match=_is_faq_intent(input) or _is_direct_faq_question(input),
        )
        if (
            isinstance(faq_payload, dict)
            and faq_payload.get("status") == "ok"
            and (_is_faq_intent(input) or _is_direct_faq_question(input))
            and not _prioritize_commercial_model_turn_over_faq(input, state)
        ):
            pending = _pending_from_requirements(input, state)
            if pending:
                faq_payload["resume_pending_action"] = pending
                faq_payload["next_required_step"] = pending
            return _decision(
                input=input,
                state=state,
                commercial_intent="faq",
                next_action="answer_faq_and_resume",
                confidence=0.9,
                reasons=["faq_before_sales_pipeline"],
                blocked_updates=_direct_question_blocked_updates(
                    input,
                    blocked_updates,
                    "direct_faq_question_does_not_update_critical_field",
                ),
                payload=faq_payload,
                pending=pending,
                blocked_actions=["no_faq_as_quote"],
                faq_tool_used=True,
                executed_tools=[{"tool": "lookup_faq", "source": "knowledge_pack", "status": "ok"}],
                tool_call_logs=[
                    _tool_log(
                        "lookup_faq",
                        {"source": "knowledge_pack", "text": input.inbound_text},
                        faq_payload,
                        0,
                    )
                ],
            )

        direct_faq_fallback = _direct_faq_safe_fallback_decision(
            input,
            state,
            blocked_updates,
        )
        if direct_faq_fallback is not None:
            return direct_faq_fallback

        quote_memory = should_recall_last_quote(
            inbound_text=input.inbound_text,
            conversation_summary=input.conversation_summary,
            extracted_data=input.extracted_data,
            credit_field=str(
                getattr(input.pipeline, "document_requirements_field", "CREDITO")
                or "CREDITO"
            ),
        )
        if quote_memory is not None:
            return _decision(
                input=input,
                state=state,
                commercial_intent="quote_memory_recall",
                next_action="quote_memory_recall",
                confidence=0.95,
                reasons=["explicit_previous_quote_reference_with_complete_memory"],
                blocked_updates=blocked_updates,
                payload=quote_memory.action_payload(),
                blocked_actions=[
                    "no_recompute_historical_quote",
                    "no_ask_clarification_when_quote_memory_complete",
                    "no_ask_field_when_quote_memory_complete",
                ],
            )

        cash_price_decision = await self._cash_price_decision(input, state, blocked_updates)
        if cash_price_decision is not None:
            return cash_price_decision

        credit_quote_decision = _credit_quote_switch_decision(input, state, blocked_updates)
        if credit_quote_decision is not None:
            return credit_quote_decision

        resolved_model_from_entities = _resolved_model_entity_value(input)
        if (
            resolved_model_from_entities
            and state.get("model")
            and not _credit_mode_switch_preserves_existing_model(input)
            and _resolved_model_entity_supported_by_text(
                input,
                resolved_model_from_entities,
                existing_model=True,
            )
            and _normalize(str(resolved_model_from_entities))
            != _normalize(str(state.get("model") or ""))
        ):
            next_action: AdvisorAction = "quote" if state.get("plan") else "ask_income_type"
            model_change_source = (
                "catalog_selection"
                if _is_catalog_selection_reference(input.inbound_text)
                else "explicit_model"
            )
            return _decision(
                input=input,
                state={**state, "model": resolved_model_from_entities},
                commercial_intent="model_change",
                next_action=next_action,
                confidence=0.95,
                reasons=["explicit_model_change_takes_priority_over_catalog_browse"],
                approved_updates={"MOTO": resolved_model_from_entities},
                blocked_updates=blocked_updates,
                payload={
                    "status": "ok",
                    "request_type": "resolve_model",
                    "model": resolved_model_from_entities,
                    "model_change_detected": True,
                    "model_change_source": model_change_source,
                    "previous_model": state.get("model"),
                    "new_model": resolved_model_from_entities,
                    "preserved_fields": [
                        field
                        for field, key in (
                            ("CREDITO", "income_type"),
                            ("ENGANCHE", "plan"),
                            ("FILTRO", "seniority_eligible"),
                        )
                        if state.get(key) not in (None, "", [], {})
                    ],
                    "invalidated_fields": ["quote_valid", "last_quote_payload"],
                    "documents_blocked_until_requote": bool(state.get("plan")),
                    "catalog_selected_model": resolved_model_from_entities,
                    "catalog_resolution_status": "resolved_from_entity",
                    "resolved_from_context": True,
                },
                blocked_actions=[
                    "explicit_model_before_catalog_browse",
                    "no_ask_documents_before_quote_without_model_plan",
                ],
            )

        if _is_vague_model_reference(input.inbound_text):
            return _vague_model_reference_decision(input, state, blocked_updates)

        if _is_generic_model_change_request(input):
            return await self._catalog_decision(
                input,
                state,
                _generic_model_change_blocked_updates(input, blocked_updates),
                category=None,
                reasons=["generic_model_change_requested_before_quote"],
            )

        catalog_category = _catalog_category(input.inbound_text)
        if _is_unresolved_catalog_reference(input.inbound_text):
            return await self._catalog_decision(
                input,
                state,
                blocked_updates,
                category=None,
                reasons=["ad_reference_requested_without_specific_model"],
                browse_intent="ad_reference",
                commercial_intent="unresolved_reference",
            )

        if resolved_model_from_entities and (_is_catalog_request(input) or catalog_category):
            next_action: AdvisorAction = "quote" if state.get("plan") else "ask_income_type"
            commercial_intent = "model_change" if state.get("model") else "model_selection"
            return _decision(
                input=input,
                state={**state, "model": resolved_model_from_entities},
                commercial_intent=commercial_intent,
                next_action=next_action,
                confidence=0.94,
                reasons=["resolved_model_entity_takes_priority_over_catalog_browse"],
                approved_updates={"MOTO": resolved_model_from_entities},
                blocked_updates=blocked_updates,
                payload={
                    "status": "ok",
                    "request_type": "resolve_model",
                    "model": resolved_model_from_entities,
                    "catalog_selected_model": resolved_model_from_entities,
                    "catalog_resolution_status": "resolved_from_entity",
                    "resolved_from_context": True,
                },
                blocked_actions=[
                    "resolved_model_before_catalog_browse",
                    "no_ask_documents_before_quote_without_model_plan",
                ],
            )

        if _is_catalog_request(input) or catalog_category:
            return await self._catalog_decision(
                input,
                state,
                blocked_updates,
                category=catalog_category,
            )

        credit_plan_reply = await self._credit_plan_selection_decision(
            input,
            state,
            blocked_updates,
        )
        if credit_plan_reply is not None:
            return credit_plan_reply

        if _document_signal(input):
            return _document_claim_clarification_decision(input, state, blocked_updates)

        if _is_credit_interest(input) and not state.get("income_type"):
            early_model_change_decision = await self._early_model_change_decision(
                input,
                state,
                blocked_updates,
            )
            if early_model_change_decision is not None:
                return early_model_change_decision
            return _decision(
                input=input,
                state={**state, "credit_intent": True},
                commercial_intent="credit_interest",
                next_action="ask_income_type",
                confidence=0.86,
                reasons=["credit_interest_without_income_type"],
                blocked_updates=blocked_updates,
                payload={
                    "status": "ok",
                    "request_type": "ask_income_type",
                    "active_purchase_mode": "credit",
                    "quote_mode": "credit",
                    "field_name": getattr(input.pipeline, "document_requirements_field", "CREDITO"),
                    "options": _credit_options(input.pipeline),
                },
                blocked_actions=[
                    "no_generic_credit_value",
                    "no_ask_documents_before_quote_without_model_plan",
                ],
            )

        model_result = await self._resolve_model(input)
        if model_result is not None:
            model_name, model_payload, logs = model_result
            updates = {"MOTO": model_name}
            next_action: AdvisorAction = "quote" if state.get("plan") else "ask_income_type"
            commercial_intent = "model_selection" if not state.get("model") else "model_change"
            payload = {"status": "ok", "request_type": "resolve_model", **model_payload}
            return _decision(
                input=input,
                state={**state, "model": model_name},
                commercial_intent=commercial_intent,
                next_action=next_action,
                confidence=0.92,
                reasons=["catalog_unique_model_resolved"],
                approved_updates=updates,
                blocked_updates=blocked_updates,
                payload=payload,
                blocked_actions=["no_ask_model_already_resolved"],
                executed_tools=[
                    {"tool": "search_catalog", "status": "ok", "mode": "resolve_model"}
                ],
                tool_call_logs=logs,
            )

        if _explicit_quote_request(input) and not state.get("model"):
            return _missing_model_for_quote_decision(input, state, blocked_updates)

        if state.get("model") and state.get("plan") and _quote_allowed(input):
            return _decision(
                input=input,
                state=state,
                commercial_intent="quote_ready",
                next_action="quote",
                confidence=0.74,
                reasons=["model_and_plan_present"],
                blocked_updates=blocked_updates,
                blocked_actions=[
                    "no_ask_model_already_resolved",
                    "no_ask_documents_before_quote_without_model_plan",
                ],
            )

        if state.get("model") and state.get("plan") and _has_direct_question(input):
            return _decision(
                input=input,
                state=state,
                commercial_intent="ambiguous_direct_question",
                next_action="clarify_ambiguous_yes_no",
                confidence=0.62,
                reasons=["direct_question_before_quote_without_policy_payload"],
                blocked_updates=blocked_updates,
                payload={
                    "status": "ok",
                    "request_type": "clarify_ambiguous_direct_question",
                    "suggested_clarification": (
                        "Me confirmas si quieres cotizacion o revisar otra cosa?"
                    ),
                },
                blocked_actions=["no_quote_when_direct_question_unresolved"],
            )

        return _decision(
            input=input,
            state=state,
            commercial_intent="unknown",
            next_action="hold_no_action",
            confidence=0.2,
            reasons=["no_commercial_advisor_override"],
            blocked_updates=blocked_updates,
            blocked_actions=["no_quote_without_model_and_plan"],
            should_override=False,
        )

    async def _cash_price_decision(
        self,
        input: SalesAdvisorDecisionInput,
        state: dict[str, Any],
        blocked_updates: list[dict[str, Any]],
    ) -> SalesAdvisorDecision | None:
        if not _is_cash_price_request(input):
            return None
        resolved_model = _resolved_model_entity_value(input)
        model = resolved_model or str(state.get("model") or "").strip()
        model_payload: dict[str, Any] = {}
        logs: list[dict[str, Any]] = []
        if not model:
            model_result = await self._resolve_model(input)
            if model_result is not None:
                model, model_payload, logs = model_result
        if not model:
            return _missing_model_for_cash_price_decision(input, state, blocked_updates)
        if model and not model_payload:
            model_payload, catalog_logs = await self._resolve_cash_catalog_payload(input, model)
            logs.extend(catalog_logs)
        if model_payload:
            cash_price = model_payload.get("cash_price_mxn")
            model_payload = {
                **model_payload,
                "name": model_payload.get("name") or model_payload.get("model") or model,
                **({"list_price_mxn": cash_price} if cash_price else {}),
            }
        next_state = {
            **state,
            "model": model,
            "active_purchase_mode": "cash",
            "quote_mode": "cash",
            "cash_quote_valid": True,
        }
        approved_updates = {"MOTO": model} if resolved_model or model_payload else {}
        return _decision(
            input=input,
            state=next_state,
            commercial_intent="cash_price_request",
            next_action="quote",
            confidence=0.95,
            reasons=["cash_price_request_uses_cash_quote_context"],
            approved_updates=approved_updates,
            blocked_updates=_direct_question_blocked_updates(
                input,
                blocked_updates,
                "cash_price_request_does_not_update_credit_fields",
            ),
            payload={
                "status": "ok",
                "request_type": "cash_price_request",
                "quote_mode": "cash",
                "active_purchase_mode": "cash",
                "cash_quote_valid": True,
                "cash_mode_blocks_credit_flow": True,
                **({"model": model} if model else {}),
                **model_payload,
            },
            blocked_actions=[
                "cash_mode_blocks_credit_flow",
                "no_ask_credit_context_for_cash_price",
                "no_ask_documents_for_cash_price",
                "no_credit_requirements_for_cash_price",
            ],
            executed_tools=[{"tool": "search_catalog", "status": "ok", "mode": "cash_model_resolution"}]
            if logs
            else [],
            tool_call_logs=logs,
        )

    async def _resolve_cash_catalog_payload(
        self,
        input: SalesAdvisorDecisionInput,
        model: str,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        clean_model = str(model or "").strip()
        if not clean_model:
            return {}, []
        started = time.perf_counter()
        result = await search_catalog(
            session=self._session,
            tenant_id=input.tenant_id,
            query=clean_model,
            embedding=None,
            limit=1,
        )
        output = (
            result.model_dump(mode="json")
            if isinstance(result, ToolNoDataResult)
            else [item.model_dump(mode="json") for item in result]
        )
        logs = [_tool_log("search_catalog", {"query": clean_model, "limit": 1}, output, started)]
        if isinstance(result, ToolNoDataResult) or not result:
            return {}, logs
        match = result[0]
        name = str(match.name or "").strip()
        if not name or _generic_model_value(name):
            return {}, logs
        return (
            {
                "model": name,
                "name": name,
                "sku": match.sku,
                "category": match.category,
                "cash_price_mxn": str(match.cash_price_mxn),
                "score": match.score,
            },
            logs,
        )

    async def _contextual_followup_decision(
        self,
        input: SalesAdvisorDecisionInput,
        state: dict[str, Any],
        blocked_updates: list[dict[str, Any]],
    ) -> SalesAdvisorDecision | None:
        normalized = _normalize(input.inbound_text)
        if normalized not in {_normalize(item) for item in _YES_NO_REPLIES | {"esa", "este", "esta"}}:
            return None
        if input.pending_confirmation:
            return None
        last_bot_message = _last_bot_message(input)
        if not last_bot_message:
            return None
        last_bot_norm = _normalize(last_bot_message)

        if _looks_like_location_offer_question(last_bot_norm):
            faq_matches = _faq_matches_for_text(
                question="ubicacion",
                knowledge_pack=input.knowledge_pack,
                allow_tag_only_match=True,
                max_matches=1,
            )
            if not faq_matches:
                return None
            payload = _faq_payload_from_matches(
                faq_matches,
                knowledge_pack=input.knowledge_pack,
                detected_intents=["ubicacion"],
                answered_intents=["ubicacion"],
                unresolved_intents=[],
                intent_stack=["ubicacion"],
                pending=_next_required_step_payload(input, state),
                next_required_step=_next_required_step_payload(input, state),
                primary_commercial_goal=_primary_commercial_goal(state),
                pending_bot_question={"type": "offer_location"},
                yes_no_context_resolution="location_confirmation",
                resolved_followup_intent="ubicacion",
                resolved_followup_entity=None,
                context_resolution_confidence=0.95,
            )
            return _decision(
                input=input,
                state=state,
                commercial_intent="contextual_location_confirmation",
                next_action="answer_faq_and_resume",
                confidence=0.95,
                reasons=["affirmative_confirmation_to_location_offer"],
                blocked_updates=blocked_updates,
                payload=payload,
                pending=_next_required_step_payload(input, state),
                blocked_actions=["no_ambiguous_yes_no_with_clear_location_context"],
                faq_tool_used=True,
                executed_tools=[{"tool": "lookup_faq", "source": "knowledge_pack", "status": "ok"}],
                tool_call_logs=[
                    _tool_log(
                        "lookup_faq",
                        {"source": "knowledge_pack", "text": "ubicacion"},
                        payload,
                        0,
                    )
                ],
            )

        confirmed_model = _confirmed_model_from_bot_message(last_bot_message)
        if confirmed_model:
            approved_updates = {"MOTO": confirmed_model}
            next_state = {**state, "model": confirmed_model}
            payload = {
                "status": "ok",
                "request_type": "resolve_model",
                "model": confirmed_model,
                "resolved_followup_intent": "modelo",
                "resolved_followup_entity": confirmed_model,
                "yes_no_context_resolution": "model_confirmation",
                "context_resolution_confidence": 0.94,
                "detected_intents": ["modelo"],
                "answered_intents": ["modelo"],
                "intent_stack": ["modelo"],
                "primary_commercial_goal": _primary_commercial_goal(next_state),
                "next_required_step": _next_required_step_payload(input, next_state),
                "pending_bot_question": {"type": "model_confirmation"},
            }
            return _decision(
                input=input,
                state=next_state,
                commercial_intent="contextual_model_confirmation",
                next_action="quote" if next_state.get("plan") else "ask_income_type",
                confidence=0.94,
                reasons=["affirmative_confirmation_to_model_confirmation"],
                approved_updates=approved_updates,
                blocked_updates=blocked_updates,
                payload=payload,
                pending=_next_required_step_payload(input, next_state),
                blocked_actions=["no_ambiguous_yes_no_with_clear_model_context"],
            )

        if _looks_like_quote_offer_question(last_bot_norm):
            resolved_model_from_entities = _resolved_model_entity_value(input)
            quote_state = dict(state)
            approved_updates: dict[str, Any] = {}
            if not quote_state.get("model") and resolved_model_from_entities:
                quote_state["model"] = resolved_model_from_entities
                approved_updates["MOTO"] = resolved_model_from_entities
            pending = _next_required_step_payload(input, quote_state)
            if quote_state.get("model") and quote_state.get("plan"):
                return _decision(
                    input=input,
                    state=quote_state,
                    commercial_intent="contextual_quote_confirmation",
                    next_action="quote",
                    confidence=0.94,
                    reasons=["affirmative_confirmation_to_quote_offer"],
                    approved_updates=approved_updates,
                    blocked_updates=blocked_updates,
                    payload={
                        "status": "ok",
                        "request_type": "quote_confirmation",
                        "detected_intents": ["quote"],
                        "answered_intents": ["quote"],
                        "intent_stack": ["quote"],
                        "yes_no_context_resolution": "quote_offer_confirmation",
                        "resolved_followup_intent": "quote",
                        "context_resolution_confidence": 0.94,
                        "primary_commercial_goal": _primary_commercial_goal(quote_state),
                        "next_required_step": pending,
                        "pending_bot_question": {"type": "quote_offer"},
                    },
                    pending=pending,
                    blocked_actions=["no_ambiguous_yes_no_with_clear_quote_offer_context"],
                )
            if pending is not None:
                field = str(pending.get("field") or "MOTO")
                next_action: AdvisorAction = "ask_income_type" if field == "CREDITO" else "ask_one_missing_field"
                payload = {
                    "status": "ok",
                    "request_type": "ask_income_type" if next_action == "ask_income_type" else "ask_one_missing_field",
                    "field_name": field,
                    "detected_intents": ["quote"],
                    "answered_intents": ["quote"],
                    "intent_stack": ["quote"],
                    "yes_no_context_resolution": "quote_offer_confirmation_missing_field",
                    "resolved_followup_intent": "quote",
                    "context_resolution_confidence": 0.9,
                    "primary_commercial_goal": _primary_commercial_goal(state),
                    "next_required_step": pending,
                    "pending_bot_question": {"type": "quote_offer"},
                }
                if next_action == "ask_income_type":
                    payload["options"] = _credit_options(input.pipeline)
                return _decision(
                    input=input,
                    state=state,
                    commercial_intent="contextual_quote_confirmation",
                    next_action=next_action,
                    confidence=0.9,
                    reasons=["affirmative_confirmation_to_quote_offer_missing_field"],
                    blocked_updates=blocked_updates,
                    payload=payload,
                    pending=pending,
                    blocked_actions=["no_soft_close_with_quote_confirmation_pending_context"],
                )
        return None

    def _multi_intent_faq_decision(
        self,
        input: SalesAdvisorDecisionInput,
        state: dict[str, Any],
        blocked_updates: list[dict[str, Any]],
    ) -> SalesAdvisorDecision | None:
        question_block = _combined_recent_inbound_block(input)
        allow_tag_only_match = _is_direct_faq_question_text(question_block) or _is_faq_intent(input)
        faq_matches = _faq_matches_for_text(
            question=question_block,
            knowledge_pack=input.knowledge_pack,
            allow_tag_only_match=allow_tag_only_match,
            max_matches=3,
        )
        requirements_requested = _is_requirements_question_text(question_block)
        explicit_quote_requested = _explicit_quote_request_text(question_block)
        if requirements_requested and not faq_matches:
            return self._requirements_decision(input, state, blocked_updates)
        if (
            explicit_quote_requested
            and requirements_requested
            and state.get("model")
            and state.get("plan")
            and not _employment_seniority_context_ready(state)
        ):
            pending = _pending_from_requirements(input, state)
            requirements = None
            result = get_missing_documents(
                pipeline=input.pipeline,
                state={"extracted_data": input.extracted_data},
            )
            if not isinstance(result, ToolNoDataResult):
                requirements = result.model_dump(mode="json")
                if pending is None:
                    pending = _pending_from_missing_documents(result)
            return _decision(
                input=input,
                state=state,
                commercial_intent="multi_intent_quote_requirements",
                next_action="quote",
                confidence=0.93,
                reasons=["quote_requested_with_requirements_requires_quote_first"],
                blocked_updates=_direct_question_blocked_updates(
                    input,
                    blocked_updates,
                    "quote_and_requirements_do_not_update_critical_field",
                ),
                payload={
                    "status": "ok",
                    "request_type": "quote_with_requirements_context",
                    "detected_intents": ["quote", "requirements"],
                    "answered_intents": ["quote", "requirements"],
                    "unresolved_intents": [],
                    "intent_stack": ["quote", "requirements"],
                    "primary_commercial_goal": _primary_commercial_goal(state),
                    "next_required_step": pending,
                    "resume_pending_action": pending,
                    "requirements_summary": (
                        "Ya con la cotizacion te digo tambien que documentos seguirian."
                    ),
                    "requirements": requirements,
                },
                pending=pending,
                blocked_actions=[
                    "quote_before_documents_when_price_and_requirements_requested",
                    "no_ask_documents_before_quote_without_model_plan",
                ],
            )
        if not faq_matches and not requirements_requested:
            return None
        if faq_matches and _prioritize_commercial_model_turn_over_faq(input, state):
            return None

        detected_intents = [match["topic"] for match in faq_matches]
        answered_intents = list(detected_intents)
        pending = _next_required_step_payload(input, state) if (_flow_active(input, state) or requirements_requested) else None
        primary_goal = _primary_commercial_goal(state)
        unresolved_intents: list[str] = []

        payload: dict[str, Any] = {}
        if faq_matches:
            payload = _faq_payload_from_matches(
                faq_matches,
                knowledge_pack=input.knowledge_pack,
                detected_intents=detected_intents,
                answered_intents=answered_intents,
                unresolved_intents=unresolved_intents,
                intent_stack=detected_intents,
                pending=pending,
                next_required_step=pending,
                primary_commercial_goal=primary_goal,
                pending_bot_question=None,
                yes_no_context_resolution=None,
                resolved_followup_intent=None,
                resolved_followup_entity=None,
                context_resolution_confidence=None,
            )
        if requirements_requested:
            if "requirements" not in detected_intents:
                detected_intents.append("requirements")
            answered_intents.append("requirements")
            payload.setdefault("detected_intents", detected_intents)
            payload["answered_intents"] = answered_intents
            payload["intent_stack"] = detected_intents
            payload["primary_commercial_goal"] = primary_goal
            payload["next_required_step"] = pending
            payload["resume_pending_action"] = pending
            if not state.get("income_type"):
                payload["requirements_summary"] = (
                    "Los requisitos dependen de como compruebas ingresos."
                )
            elif not state.get("model"):
                payload["requirements_summary"] = (
                    "Ya con tu plan, solo falta el modelo para decirte bien como avanzar."
                )
            else:
                result = get_missing_documents(
                    pipeline=input.pipeline,
                    state={"extracted_data": input.extracted_data},
                )
                if not isinstance(result, ToolNoDataResult):
                    payload["requirements"] = result.model_dump(mode="json")
                    if pending is None:
                        pending = _pending_from_missing_documents(result)
                        payload["resume_pending_action"] = pending
                        payload["next_required_step"] = pending
            specific_answer = _specific_requirements_followup_answer(
                inbound_text=input.inbound_text,
                requirements_payload=payload.get("requirements")
                if isinstance(payload.get("requirements"), dict)
                else {"missing": (pending or {}).get("missing") or (pending or {}).get("required") or []},
            )
            if specific_answer:
                payload["answer"] = specific_answer
                payload["source"] = "requirements_followup"
                if "requirements" not in payload["answered_intents"]:
                    payload["answered_intents"].append("requirements")

        if not payload:
            return None

        return _decision(
            input=input,
            state=state,
            commercial_intent="multi_intent_faq",
            next_action="answer_faq_and_resume",
            confidence=0.92,
            reasons=["multi_intent_questions_answered_before_resuming_flow"],
            blocked_updates=_direct_question_blocked_updates(
                input,
                blocked_updates,
                "multi_intent_questions_do_not_update_critical_field",
            ),
            payload=payload,
            pending=pending,
            blocked_actions=["no_soft_close_with_active_multi_intent"],
            faq_tool_used=bool(faq_matches),
            executed_tools=[{"tool": "lookup_faq", "source": "knowledge_pack", "status": "ok"}]
            if faq_matches
            else [],
            tool_call_logs=[
                _tool_log(
                    "lookup_faq",
                    {"source": "knowledge_pack", "text": question_block},
                    payload,
                    0,
                )
            ]
            if faq_matches
            else [],
        )

    async def _explicit_down_payment_change_decision(
        self,
        input: SalesAdvisorDecisionInput,
        state: dict[str, Any],
        blocked_updates: list[dict[str, Any]],
        requested: ExplicitDownPaymentChange,
    ) -> SalesAdvisorDecision | None:
        model = str(state.get("model") or "").strip()
        income_type = str(state.get("income_type") or "").strip()
        if not model or not income_type:
            return None
        minimum_plan_code = minimum_plan_code_for_credit(
            pipeline=input.pipeline,
            credit_value=income_type,
        )
        if not minimum_plan_code:
            return None
        if not requested_plan_meets_minimum(
            requested=requested,
            minimum_plan_code=minimum_plan_code,
        ):
            minimum_quote_decision = await self._quote_for_model_and_plan(
                input=input,
                state=state,
                blocked_updates=blocked_updates,
                model=model,
                plan_code=minimum_plan_code,
                commercial_intent="explicit_down_payment_below_minimum",
                reasons=["explicit_down_payment_below_credit_minimum"],
                approved_updates=None,
                blocked_actions=[
                    "no_update_enganche_below_credit_minimum",
                    "no_quote_below_credit_minimum",
                ],
            )
            if minimum_quote_decision is not None:
                return minimum_quote_decision
            return _decision(
                input=input,
                state=state,
                commercial_intent="explicit_down_payment_below_minimum",
                next_action="clarify_ambiguous_yes_no",
                confidence=0.95,
                reasons=["explicit_down_payment_below_credit_minimum_without_quote"],
                blocked_updates=blocked_updates,
                payload={
                    "status": "ok",
                    "request_type": "clarify_ambiguous_yes_no",
                    "suggested_clarification": (
                        f"Para {income_type}, el enganche minimo es {minimum_plan_code}. "
                        "Puedo continuar con ese plan."
                    ),
                },
                blocked_actions=[
                    "no_quote_below_credit_minimum",
                    "no_update_enganche_below_credit_minimum",
                ],
            )

        catalog_result = await search_catalog(
            session=self._session,
            tenant_id=input.tenant_id,
            query=model,
            embedding=None,
            limit=1,
        )
        if isinstance(catalog_result, ToolNoDataResult) or not catalog_result:
            return None
        selected_model = catalog_result[0]
        quote_result = await quote_catalog_plan(
            session=self._session,
            tenant_id=input.tenant_id,
            sku=selected_model.sku,
            plan_code=requested.requested_plan_code,
        )
        quote_payload = quote_result.model_dump(mode="json")
        if not quote_payload_has_plan(quote_payload, requested.requested_plan_code):
            return _decision(
                input=input,
                state=state,
                commercial_intent="explicit_down_payment_unavailable",
                next_action="clarify_ambiguous_yes_no",
                confidence=0.92,
                reasons=["explicit_down_payment_plan_not_in_catalog"],
                blocked_updates=blocked_updates,
                payload={
                    "status": "ok",
                    "request_type": "clarify_ambiguous_yes_no",
                    "suggested_clarification": (
                        f"El plan {requested.requested_plan_code} no esta disponible "
                        f"para {model}. Puedo revisar los planes disponibles."
                    ),
                },
                blocked_actions=[
                    "no_quote_unavailable_plan",
                    "no_update_enganche_for_unavailable_plan",
                ],
            )

        return _decision(
            input=input,
            state={**state, "plan": requested.requested_plan_code},
            commercial_intent="explicit_down_payment_change",
            next_action="quote",
            confidence=0.95,
            reasons=["explicit_down_payment_change_valid_catalog_plan"],
            approved_updates={"ENGANCHE": requested.requested_plan_code},
            blocked_updates=blocked_updates,
            blocked_actions=[
                "no_keep_previous_down_payment_after_explicit_change",
                "no_ask_income_type_when_credit_present",
                "no_quote_memory_recall_for_explicit_plan_change",
            ],
        )

    async def _quote_for_model_and_plan(
        self,
        *,
        input: SalesAdvisorDecisionInput,
        state: dict[str, Any],
        blocked_updates: list[dict[str, Any]],
        model: str,
        plan_code: str,
        commercial_intent: str,
        reasons: list[str],
        approved_updates: dict[str, Any] | None,
        blocked_actions: list[str],
    ) -> SalesAdvisorDecision | None:
        catalog_result = await search_catalog(
            session=self._session,
            tenant_id=input.tenant_id,
            query=model,
            embedding=None,
            limit=1,
        )
        if isinstance(catalog_result, ToolNoDataResult) or not catalog_result:
            return None
        selected_model = catalog_result[0]
        quote_result = await quote_catalog_plan(
            session=self._session,
            tenant_id=input.tenant_id,
            sku=selected_model.sku,
            plan_code=plan_code,
        )
        quote_payload = quote_result.model_dump(mode="json")
        if not quote_payload_has_plan(quote_payload, plan_code):
            return None
        return _decision(
            input=input,
            state=state,
            commercial_intent=commercial_intent,
            next_action="quote",
            confidence=0.95,
            reasons=reasons,
            approved_updates=approved_updates,
            blocked_updates=blocked_updates,
            payload=quote_payload,
            blocked_actions=blocked_actions,
            executed_tools=[{"tool": "quote", "status": "ok", "mode": "explicit_down_payment"}],
            tool_call_logs=[
                _tool_log(
                    "quote",
                    {"model": model, "plan_code": plan_code},
                    quote_payload,
                    0,
                )
            ],
        )

    async def _catalog_decision(
        self,
        input: SalesAdvisorDecisionInput,
        state: dict[str, Any],
        blocked_updates: list[dict[str, Any]],
        *,
        category: str | None,
        reasons: list[str] | None = None,
        browse_intent: str | None = None,
        commercial_intent: str | None = None,
    ) -> SalesAdvisorDecision:
        started = time.perf_counter()
        resolved_browse_intent = browse_intent or (
            "catalog_style" if category else "catalog_overview"
        )
        current_model = str(state.get("model") or "").strip()
        browse_category = category
        normalized_excluded_model = _normalize(current_model) if current_model else ""
        if resolved_browse_intent == "catalog_more" and current_model and not browse_category:
            current_match = await search_catalog(
                session=self._session,
                tenant_id=input.tenant_id,
                query=current_model,
                embedding=None,
                limit=1,
            )
            if isinstance(current_match, list) and current_match:
                browse_category = str(getattr(current_match[0], "category", "") or "").strip() or None
        result = await list_catalog(
            session=self._session,
            tenant_id=input.tenant_id,
            category=browse_category,
            query="",
            limit=50,
        )
        payload = result.model_dump(mode="json")
        if payload.get("status") == "ok":
            models = payload.get("models") or []
            if normalized_excluded_model:
                models = [
                    item
                    for item in models
                    if not (
                        isinstance(item, dict)
                        and _normalize(str(item.get("name") or item.get("sku") or "").strip())
                        == normalized_excluded_model
                    )
                ]
            preview = models[:10] if isinstance(models, list) else []
            payload = {
                "status": "ok",
                "request_type": "catalog_browse",
                "browse_intent": resolved_browse_intent,
                "query": browse_category or "",
                "total_results": len(models) if isinstance(models, list) else 0,
                "shown_results": len(preview),
                "has_more": isinstance(models, list) and len(models) > len(preview),
                "catalog_url": input.catalog_url or "",
                "results": preview,
                "pending_question_options": [
                    str(item.get("name") or item.get("sku") or "").strip()
                    for item in preview
                    if isinstance(item, dict)
                    and str(item.get("name") or item.get("sku") or "").strip()
                ][:3],
                "catalog_resolution_status": "browse",
                "catalog_candidate_count": len(models) if isinstance(models, list) else 0,
                "source": payload.get("source"),
            }
        else:
            payload = {
                **payload,
                "request_type": "catalog_browse",
                "browse_intent": resolved_browse_intent,
                "query": browse_category or "",
                "total_results": 0,
                "shown_results": 0,
                "has_more": False,
                "results": [],
                "pending_question_options": [],
                "catalog_resolution_status": "browse_empty",
                "catalog_candidate_count": 0,
            }
        intent = "catalog_filter" if category else "catalog_browse"
        return _decision(
            input=input,
            state=state,
            commercial_intent=commercial_intent or intent,
            next_action="catalog_filter" if category else "catalog_browse",
            confidence=0.88,
            reasons=reasons or ["catalog_requested_before_pipeline_fields"],
            blocked_updates=[
                *blocked_updates,
                *[
                    _blocked_update(field, value, "catalog_request_does_not_resolve_model")
                    for field, value in _nlu_entity_values(input).items()
                    if str(field).upper() == "MOTO"
                ],
            ],
            payload=payload,
            blocked_actions=["no_ask_generic_model_when_catalog_requested"],
            catalog_category=browse_category,
            catalog_browse_intent=payload.get("browse_intent"),
            executed_tools=[
                {"tool": "listCatalog", "status": payload.get("status"), "mode": "catalog_browse"},
                {
                    "tool": "search_catalog",
                    "status": payload.get("status"),
                    "mode": "catalog_browse_facade_alias",
                },
            ],
            tool_call_logs=[
                _tool_log(
                    "listCatalog",
                    {"category": browse_category, "query": "", "limit": 50},
                    payload,
                    started,
                )
            ],
        )

    def _requirements_decision(
        self,
        input: SalesAdvisorDecisionInput,
        state: dict[str, Any],
        blocked_updates: list[dict[str, Any]],
    ) -> SalesAdvisorDecision:
        quote_context = _documents_quote_context(input, state)
        ambiguity_signals = _income_disambiguation_signals(input.inbound_text)
        if ambiguity_signals.needs_income_disambiguation:
            pending = {"type": "ask_field", "field": "CREDITO"}
            blocked_reason = "requirements_need_income_disambiguation"
            answer = _requirements_answer_only_text(
                blocked_reason=blocked_reason,
                signals=ambiguity_signals,
            )
            payload = {
                "status": "ok",
                "request_type": "requirements_answer_only",
                "topic": "requirements",
                "answer": answer,
                "answers": [
                    {
                        "topic": "requirements",
                        "answer": answer,
                        "source": "requirements_guard",
                        "confidence": 1.0,
                    }
                ],
                "answered_intents": ["requirements", "income_clarification"],
                "resume_pending_action": pending,
                "next_required_step": pending,
                "policy_trace": _requirements_policy_trace(
                    blocked_reason=blocked_reason,
                    quote_context=quote_context,
                    pending=pending,
                    signals=ambiguity_signals,
                ),
            }
            return _decision(
                input=input,
                state=state,
                commercial_intent="requirements_need_credit_context",
                next_action="answer_faq_and_resume",
                confidence=0.9,
                reasons=["requirements_question_needs_income_disambiguation_first"],
                blocked_updates=_direct_question_blocked_updates(
                    input,
                    blocked_updates,
                    "requirements_question_without_income_disambiguation",
                ),
                payload=payload,
                pending=pending,
                blocked_actions=[
                    "formal_documents_blocked_until_income_resolved",
                    "documents_after_quote_only",
                    "no_credit_plan_write_when_income_ambiguous",
                    "no_ask_documents_before_quote_without_model_plan",
                    "no_quote_without_model_and_plan",
                ],
            )
        if not state.get("income_type") or not state.get("plan"):
            pending = {"type": "ask_field", "field": "CREDITO"}
            blocked_reason = "requirements_need_credit_context"
            answer = _requirements_answer_only_text(blocked_reason=blocked_reason)
            payload = {
                "status": "ok",
                "request_type": "requirements_answer_only",
                "topic": "requirements",
                "answer": answer,
                "answers": [
                    {
                        "topic": "requirements",
                        "answer": answer,
                        "source": "requirements_guard",
                        "confidence": 1.0,
                    }
                ],
                "answered_intents": ["requirements"],
                "resume_pending_action": pending,
                "next_required_step": pending,
                "policy_trace": _requirements_policy_trace(
                    blocked_reason=blocked_reason,
                    quote_context=quote_context,
                    pending=pending,
                ),
            }
            return _decision(
                input=input,
                state=state,
                commercial_intent="requirements_need_credit_context",
                next_action="answer_faq_and_resume",
                confidence=0.84,
                reasons=["requirements_question_needs_credit_context_first"],
                blocked_updates=_direct_question_blocked_updates(
                    input,
                    blocked_updates,
                    "requirements_question_without_plan_does_not_update_critical_field",
                ),
                payload=payload,
                pending=pending,
                blocked_actions=[
                    "formal_documents_blocked_until_income_resolved",
                    "documents_after_quote_only",
                    "no_ask_documents_before_quote_without_model_plan",
                    "no_quote_without_model_and_plan",
                ],
            )
        if not state.get("model"):
            pending = {"type": "ask_field", "field": "MOTO"}
            blocked_reason = "requirements_need_model_context"
            answer = _requirements_answer_only_text(blocked_reason=blocked_reason)
            payload = {
                "status": "ok",
                "request_type": "requirements_answer_only",
                "topic": "requirements",
                "answer": answer,
                "answers": [
                    {
                        "topic": "requirements",
                        "answer": answer,
                        "source": "requirements_guard",
                        "confidence": 1.0,
                    }
                ],
                "answered_intents": ["requirements"],
                "resume_pending_action": pending,
                "next_required_step": pending,
                "policy_trace": _requirements_policy_trace(
                    blocked_reason=blocked_reason,
                    quote_context=quote_context,
                    pending=pending,
                ),
            }
            return _decision(
                input=input,
                state=state,
                commercial_intent="requirements_need_model_context",
                next_action="answer_faq_and_resume",
                confidence=0.84,
                reasons=["requirements_question_needs_model_before_documents"],
                blocked_updates=_direct_question_blocked_updates(
                    input,
                    blocked_updates,
                    "requirements_question_without_model_does_not_update_critical_field",
                ),
                payload=payload,
                pending=pending,
                blocked_actions=[
                    "documents_after_quote_only",
                    "no_ask_documents_before_quote_without_model_plan",
                    "no_quote_without_model_and_plan",
                ],
            )
        if _is_document_purpose_or_refusal_question(input.inbound_text):
            pending = _pending_from_requirements(input, state)
            answer = (
                "Te explico: los documentos se usan para revisar identidad, domicilio y que el "
                "plan corresponda a tu forma de comprobar ingresos. No es para presionarte; "
                "primero dejamos clara la cotizacion y ya con eso te digo que conviene mandar."
            )
            payload = {
                "status": "ok",
                "request_type": "requirements_answer_only",
                "topic": "requirements",
                "answer": answer,
                "answers": [
                    {
                        "topic": "requirements",
                        "answer": answer,
                        "source": "document_purpose_guard",
                        "confidence": 1.0,
                    }
                ],
                "answered_intents": ["requirements", "documents"],
                "resume_pending_action": pending,
                "next_required_step": pending,
                "policy_trace": _requirements_policy_trace(
                    blocked_reason="document_purpose_answered",
                    quote_context=quote_context,
                    pending=pending,
                ),
            }
            return _decision(
                input=input,
                state=state,
                commercial_intent="document_purpose_question",
                next_action="answer_faq_and_resume",
                confidence=0.9,
                reasons=["document_refusal_or_purpose_question_answered_before_resume"],
                blocked_updates=_direct_question_blocked_updates(
                    input,
                    blocked_updates,
                    "document_purpose_question_does_not_update_critical_field",
                ),
                payload=payload,
                pending=pending,
                blocked_actions=["current_question_answered_before_flow_resume"],
            )
        if quote_context["quote_required_before_documents"]:
            return _decision(
                input=input,
                state=state,
                commercial_intent="requirements_need_quote_first",
                next_action="quote",
                confidence=0.9,
                reasons=["requirements_question_requires_quote_before_documents"],
                blocked_updates=_direct_question_blocked_updates(
                    input,
                    blocked_updates,
                    "requirements_question_requires_quote_before_documents",
                ),
                payload={
                    "policy_trace": _requirements_policy_trace(
                        blocked_reason="quote_required_before_documents",
                        quote_context=quote_context,
                        pending=None,
                    )
                },
                blocked_actions=[
                    "quote_required_before_documents",
                    "documents_after_quote_only",
                    "no_ask_documents_before_quote_without_model_plan",
                ],
            )
        pending = _pending_from_requirements(input, state)
        payload: dict[str, Any] = {
            "status": "ok",
            "request_type": "ask_missing_document",
            "pending_to_resume": pending,
        }
        result = get_missing_documents(
            pipeline=input.pipeline,
            state={"extracted_data": input.extracted_data},
        )
        if not isinstance(result, ToolNoDataResult):
            payload["requirements"] = result.model_dump(mode="json")
            if pending is None:
                pending = _pending_from_missing_documents(result)
                payload["pending_to_resume"] = pending
            specific_answer = _specific_requirements_followup_answer(
                inbound_text=input.inbound_text,
                requirements_payload=payload.get("requirements"),
            )
            if specific_answer:
                payload["answer"] = specific_answer
                payload["source"] = "requirements_followup"
                payload["answered_intents"] = ["requirements"]
        payload["policy_trace"] = _requirements_policy_trace(
            blocked_reason="documents_allowed_after_quote",
            quote_context=quote_context,
            pending=pending,
        )
        return _decision(
            input=input,
            state=state,
            commercial_intent="requirements_question",
            next_action="ask_missing_document",
            confidence=0.84,
            reasons=["requirements_question_before_quote"],
            blocked_updates=_direct_question_blocked_updates(
                input,
                blocked_updates,
                "requirements_question_does_not_update_critical_field",
            ),
            payload=payload,
            pending=pending,
            blocked_actions=["no_ask_documents_before_quote_without_model_plan"],
            executed_tools=[{"tool": "getMissingDocuments", "status": payload.get("status")}],
            tool_call_logs=[
                _tool_log(
                    "getMissingDocuments",
                    {"source": "advisor_requirements_question"},
                    payload,
                    0,
                )
            ],
        )

    def _post_quote_progress_decision(
        self,
        input: SalesAdvisorDecisionInput,
        state: dict[str, Any],
        blocked_updates: list[dict[str, Any]],
    ) -> SalesAdvisorDecision | None:
        if not (state.get("model") and state.get("plan")):
            return None
        pending = _pending_from_requirements(input, state)
        if not _is_post_quote_progress_followup(input.inbound_text):
            if not _is_affirmative_post_quote_requirements_followup(
                text=input.inbound_text,
                last_bot_message=_last_bot_message(input),
                pending=pending,
            ):
                return None
        if _is_affirmative_post_quote_requirements_followup(
            text=input.inbound_text,
            last_bot_message=_last_bot_message(input),
            pending=pending,
        ):
            return self._requirements_decision(input, state, blocked_updates)
        if pending is not None:
            return self._requirements_decision(input, state, blocked_updates)
        if not _is_post_quote_progress_followup(input.inbound_text):
            return None
        if _employment_seniority_context_ready(state):
            return _decision(
                input=input,
                state=state,
                commercial_intent="post_quote_progress_followup",
                next_action="ask_one_missing_field",
                confidence=0.82,
                reasons=["post_quote_progress_requires_employment_seniority_before_documents"],
                blocked_updates=blocked_updates,
                payload={
                    "status": "ok",
                    "request_type": "ask_one_missing_field",
                    "field_name": ANTIGUEDAD_LABORAL_FIELD_KEY,
                    "field_description": "Antiguedad laboral",
                },
                pending={"type": "ask_field", "field": ANTIGUEDAD_LABORAL_FIELD_KEY},
                blocked_actions=[
                    "no_repeat_quote_for_progress_followup",
                    "no_documents_before_employment_seniority",
                ],
            )
        return self._requirements_decision(input, state, blocked_updates)

    def _acknowledgement_decision(
        self,
        input: SalesAdvisorDecisionInput,
        state: dict[str, Any],
        blocked_updates: list[dict[str, Any]],
    ) -> SalesAdvisorDecision | None:
        if _should_defer_acknowledgement_to_model_resolution(input, state):
            return None
        last_bot_message = _last_bot_message(input)
        result = classify_acknowledgement(
            AcknowledgementPolicyRequest(
                user_message=input.inbound_text,
                last_bot_message=last_bot_message,
                recent_history=_recent_history(input),
                current_state=input.extracted_data,
                pending_confirmation=input.pending_confirmation,
                pending_confirmation_updates=dict(
                    input.metadata.get("pending_confirmation_updates") or {}
                ),
                operational_intent_category=str(
                    getattr(input.operational_intent, "intent_category", "") or ""
                ),
                nlu_intent=str(getattr(input.nlu, "intent", "") or ""),
            )
        )
        if result.classification == "no_ack_match":
            return None
        if (
            result.classification == "valid_confirmation"
            and result.action_override == "answer_requirements"
        ):
            return self._requirements_decision(input, state, blocked_updates)
        resolution = resolve_acknowledgement_context(
            ack_class=result.classification,
            last_bot_question=last_bot_message,
            current_stage=str(input.current_stage or ""),
            contact_fields={
                "CREDITO": state.get("income_type"),
                "ENGANCHE": state.get("plan"),
                "MOTO": state.get("model"),
                "FILTRO": state.get("seniority_eligible"),
                ANTIGUEDAD_LABORAL_FIELD_KEY: state.get("employment_seniority"),
            },
            last_quote_signature=_last_quote_signature(input),
            pending_field=_pending_acknowledgement_field(last_bot_message, state),
            documents_state=_documents_state_for_acknowledgement(input, state, last_bot_message),
        )
        if resolution is None:
            return None
        action_payload = dict(resolution.payload)
        if resolution.advisor_action == "soft_close":
            action_payload.setdefault("status", "ok")
            action_payload.setdefault("request_type", "soft_close")
            action_payload.setdefault("suggested_response", result.outbound_hint)
            action_payload.setdefault("classification", result.classification)
            blocked_reason = "soft_close_does_not_update_state"
        elif resolution.advisor_action == "clarify_ambiguous_yes_no":
            action_payload.setdefault("status", "ok")
            action_payload.setdefault("request_type", "clarify_ambiguous_yes_no")
            action_payload.setdefault("clarification_type", result.classification)
            action_payload.setdefault("target_field", result.target_field)
            action_payload.setdefault("suggested_clarification", result.outbound_hint)
            blocked_reason = "ambiguous_acknowledgement_does_not_update_state"
        else:
            action_payload.setdefault("status", "ok")
            blocked_reason = "contextual_acknowledgement_does_not_update_state"
        return _decision(
            input=input,
            state=state,
            commercial_intent=resolution.commercial_intent,
            next_action=resolution.advisor_action,
            confidence=resolution.confidence,
            reasons=[resolution.reason],
            blocked_updates=_acknowledgement_blocked_updates(blocked_updates, blocked_reason),
            payload=action_payload,
            pending=resolution.pending_to_resume,
            blocked_actions=resolution.forbidden_actions_applied,
        )
        return None

    async def _process_document(
        self,
        input: SalesAdvisorDecisionInput,
        state: dict[str, Any],
        blocked_updates: list[dict[str, Any]],
    ) -> SalesAdvisorDecision:
        attachment_intent = _attachment_intent(input)
        updates = _document_updates(input)
        merged_state = {**state, **_state_from_updates(updates)}
        pending = _pending_from_requirements(input, merged_state, updates=updates)
        payload = {
            "status": "ok",
            "request_type": "process_document",
            "received_documents": [
                {"key": key, "label": _document_label(input.pipeline, key), "status": value}
                for key, value in updates.items()
            ],
            "rejected_attachments": [
                {"label": label, "reason": "blurry_or_untrusted_attachment"}
                for label in attachment_intent.rejected_labels
            ],
            "attachment_intent": {
                "labels": list(attachment_intent.labels),
                "kinds": list(attachment_intent.kinds),
                "reason_codes": list(attachment_intent.reason_codes),
            },
            "pending_to_resume": pending,
        }
        has_deferred_attachment = bool(attachment_intent.rejected_labels) and not updates
        return _decision(
            input=input,
            state=merged_state,
            commercial_intent="documents",
            next_action=(
                "process_document"
                if (updates or has_deferred_attachment)
                else "ask_missing_document"
            ),
            confidence=0.86 if updates else 0.7,
            reasons=[
                "document_turn_processed_before_quote",
                *list(attachment_intent.reason_codes),
            ],
            approved_updates=updates,
            blocked_updates=blocked_updates,
            payload=payload,
            pending=pending,
            blocked_actions=["no_documents_as_purchase_intent", "no_quote_default_for_document"],
        )

    async def _resolve_model(
        self,
        input: SalesAdvisorDecisionInput,
        *,
        allow_credit_interest: bool = False,
    ) -> tuple[str, dict[str, Any], list[dict[str, Any]]] | None:
        values = _flat_values(input.extracted_data)
        existing_model = values.get("MOTO")
        model_change_requested = bool(
            existing_model and _looks_like_model_change(input.inbound_text)
        )
        credit_interest = _is_credit_interest(input)
        if (
            (credit_interest and not model_change_requested and not allow_credit_interest)
            or _is_catalog_request(input)
            or _catalog_category(input.inbound_text)
        ):
            return None
        if existing_model and not model_change_requested:
            return None
        if not _has_model_resolution_signal(
            text=input.inbound_text,
            allow_credit_interest=allow_credit_interest,
            existing_model=bool(existing_model),
        ):
            return None

        queries = _model_queries(input.inbound_text)
        if credit_interest and model_change_requested:
            queries = _dedupe(
                [*_credit_preserving_model_change_queries(input.inbound_text), *queries]
            )
        logs: list[dict[str, Any]] = []
        for query in queries:
            started = time.perf_counter()
            result = await search_catalog(
                session=self._session,
                tenant_id=input.tenant_id,
                query=query,
                embedding=None,
                limit=3,
            )
            output = (
                result.model_dump(mode="json")
                if isinstance(result, ToolNoDataResult)
                else [item.model_dump(mode="json") for item in result]
            )
            logs.append(_tool_log("search_catalog", {"query": query, "limit": 3}, output, started))
            if isinstance(result, ToolNoDataResult) or len(result) != 1:
                continue
            match = result[0]
            name = str(match.name or "").strip()
            if not name or _generic_model_value(name):
                continue
            return (
                name,
                {
                    "model": name,
                    "sku": match.sku,
                    "category": match.category,
                    "cash_price_mxn": str(match.cash_price_mxn),
                    "score": match.score,
                },
                logs,
            )
        return None

    async def _credit_plan_selection_decision(
        self,
        input: SalesAdvisorDecisionInput,
        state: dict[str, Any],
        blocked_updates: list[dict[str, Any]],
    ) -> SalesAdvisorDecision | None:
        if state.get("income_type"):
            return None
        normalized_inbound = _normalize(input.inbound_text)
        if (
            _recent_income_disambiguation_context(input)
            and _deposit_formal_income_confirmation_signal(input.inbound_text)
        ):
            return await self._build_payroll_card_override_decision(
                input,
                state,
                blocked_updates,
            )
        ambiguity_signals = _income_disambiguation_signals(input.inbound_text)
        if ambiguity_signals.needs_income_disambiguation:
            return self._income_disambiguation_decision(
                input,
                state,
                blocked_updates,
                signals=ambiguity_signals,
            )
        if (
            _recent_dual_income_context(input)
            and not _dual_income_selection_signal(input.inbound_text)
        ):
            return self._income_disambiguation_decision(
                input,
                state,
                blocked_updates,
                signals=IncomeDisambiguationSignals(
                    income_ambiguity=True,
                    dual_income_detected=True,
                    needs_income_disambiguation=True,
                    credit_plan_write_blocked_reason="dual_income_detected",
                ),
                reasons=["dual_income_context_still_requires_explicit_income_choice"],
            )
        if (
            _payroll_card_signal(input.inbound_text)
            or (
            _recent_income_disambiguation_context(input) and "tarjeta" in set(normalized_inbound.split())
            )
        ):
            return await self._build_payroll_card_override_decision(
                input,
                state,
                blocked_updates,
            )
        if (
            _recent_income_disambiguation_context(input)
            and any(term in normalized_inbound for term in ("conviene", "comprobable", "aplica", "plan"))
        ):
            return self._income_disambiguation_decision(
                input,
                state,
                blocked_updates,
                signals=IncomeDisambiguationSignals(
                    income_ambiguity=True,
                    dual_income_detected=True,
                    needs_income_disambiguation=True,
                    credit_plan_write_blocked_reason="dual_income_detected",
                ),
                reasons=["income_disambiguation_followup_still_requires_income_choice"],
            )
        if _guardia_signal(input.inbound_text):
            return await self._build_guardia_override_decision(
                input,
                state,
                blocked_updates,
            )
        if _positive_receipts_signal(input.inbound_text):
            return await self._build_positive_receipts_override_decision(
                input,
                state,
                blocked_updates,
            )
        if _negative_receipts_signal(input.inbound_text):
            return await self._build_negative_receipts_override_decision(
                input,
                state,
                blocked_updates,
            )
        credit_plan = resolve_credit_plan(
            input_text=input.inbound_text,
            pipeline=input.pipeline,
            context={"extracted_data": input.extracted_data},
        )
        if isinstance(credit_plan, ToolNoDataResult):
            return None
        if (
            credit_plan.selection_key == "Nomina Recibos"
            and _negative_receipts_signal(input.inbound_text)
        ):
            return await self._build_negative_receipts_override_decision(
                input,
                state,
                blocked_updates,
            )
        if _needs_payroll_receipts_confirmation(
            inbound_text=input.inbound_text,
            credit_plan_key=credit_plan.selection_key,
        ):
            pending_confirmation = {
                "yes": {"CREDITO": "Nomina Tarjeta", "ENGANCHE": "10%"},
                "no": {"CREDITO": "Sin Comprobantes", "ENGANCHE": "20%"},
            }
            return _decision(
                input=input,
                state=state,
                commercial_intent="credit_plan_requires_receipts_confirmation",
                next_action="clarify_ambiguous_yes_no",
                confidence=0.84,
                reasons=["payroll_card_requires_receipts_confirmation"],
                blocked_updates=blocked_updates,
                payload={
                    "status": "ok",
                    "request_type": "clarify_ambiguous_yes_no",
                    "clarification_type": "payroll_receipts",
                    "target_field": "CREDITO",
                    "suggested_clarification": "Te dan recibos de nomina? Si o no.",
                    "pending_confirmation_set": pending_confirmation,
                },
                blocked_actions=[
                    "no_write_credit_plan_without_payroll_receipts_confirmation",
                    "no_quote_without_model_and_plan",
                ],
            )
        payload = credit_plan.model_dump(mode="json")
        updates = dict(credit_plan.field_updates)
        if _recent_income_disambiguation_context(input):
            _mark_dual_income_selection_resolved(
                payload,
                selection_key=str(updates.get("CREDITO") or credit_plan.selection_key or ""),
                confidence=float(getattr(credit_plan, "confidence", 0.0) or 0.0),
            )
        executed_tools = [{"tool": "resolve_credit_plan", "status": "ok"}]
        tool_call_logs = [
            _tool_log(
                "resolve_credit_plan",
                {"input_text": input.inbound_text},
                payload,
                0,
            )
        ]
        if _should_attempt_model_resolution_with_credit_context(input):
            model_result = await self._resolve_model(input, allow_credit_interest=True)
            if model_result is not None:
                model_name, _model_payload, model_logs = model_result
                updates["MOTO"] = model_name
                executed_tools.append(
                    {"tool": "search_catalog", "status": "ok", "mode": "resolve_model"}
                )
                tool_call_logs.extend(model_logs)
        next_state = {**state, **_state_from_updates(updates)}
        pending = _next_missing_after_credit(updates, state)
        payload["pending_to_resume"] = pending
        if not next_state.get("model"):
            pending = {"type": "ask_field", "field": "MOTO"}
            payload["pending_to_resume"] = pending
            payload["request_type"] = "ask_one_missing_field"
            payload["field_name"] = "MOTO"
            payload["prompt_override"] = (
                "Listo, ya tengo tu plan. Solo dime que modelo quieres cotizar."
            )
            next_action: AdvisorAction = "ask_one_missing_field"
        elif (
            state.get("model")
            and next_state.get("plan")
            and pending is None
            and (
                _recent_dual_income_context(input)
                or _employment_seniority_known(state)
                or str(updates.get("CREDITO") or credit_plan.selection_key or "").strip()
                == "Nomina Tarjeta"
            )
        ):
            next_action = "quote"
        else:
            next_action = "resolve_credit_plan"
        return _decision(
            input=input,
            state=next_state,
            commercial_intent="credit_option_selection",
            next_action=next_action,
            confidence=credit_plan.confidence,
            reasons=[
                "credit_plan_alias_resolved_from_pipeline_selection_catalog",
                *(
                    ["resolved_plan_with_existing_model_quotes_next"]
                    if next_action == "quote"
                    else []
                ),
            ],
            approved_updates=updates,
            blocked_updates=blocked_updates,
            payload=payload,
            pending=pending,
            blocked_actions=[
                "no_ask_antiguedad_for_sin_comprobantes_20",
                "no_generic_credit_value",
            ],
            executed_tools=executed_tools,
            tool_call_logs=tool_call_logs,
        )

    async def _build_plan_override_decision(
        self,
        input: SalesAdvisorDecisionInput,
        state: dict[str, Any],
        blocked_updates: list[dict[str, Any]],
        *,
        selection_key: str,
        selection_label: str,
        plan: str,
        confidence: float,
        matched_alias: str,
        mode: str,
        reason_code: str,
        blocked_action_reasons: list[str],
    ) -> SalesAdvisorDecision:
        updates: dict[str, Any] = {"CREDITO": selection_key, "ENGANCHE": plan}
        merged_state = {**state, **_state_from_updates(updates)}
        approved_updates: dict[str, Any] = dict(updates)
        payload: dict[str, Any] = {
            "status": "ok",
            "type": "credit_plan_resolution",
            "input": input.inbound_text,
            "field_name": getattr(input.pipeline, "document_requirements_field", "CREDITO"),
            "selection_key": selection_key,
            "selection_label": selection_label,
            "matched_alias": matched_alias,
            "confidence": confidence,
            "field_updates": dict(updates),
            "source": {
                "tool": "resolve_credit_plan",
                "mode": mode,
            },
        }
        if _recent_income_disambiguation_context(input):
            _mark_dual_income_selection_resolved(
                payload,
                selection_key=selection_key,
                confidence=confidence,
            )
        executed_tools = [{"tool": "resolve_credit_plan", "status": "ok", "mode": mode}]
        tool_call_logs = [
            _tool_log(
                "resolve_credit_plan",
                {"input_text": input.inbound_text, "override": mode},
                payload,
                0,
            )
        ]

        seniority = parse_employment_seniority(input.inbound_text)
        if seniority is not None:
            approved_updates.update(_seniority_updates(seniority))
            merged_state["employment_seniority"] = seniority.display_value

        if _should_attempt_model_resolution_with_credit_context(input):
            model_result = await self._resolve_model(input, allow_credit_interest=True)
            if model_result is not None:
                model_name, _model_payload, model_logs = model_result
                updates["MOTO"] = model_name
                approved_updates["MOTO"] = model_name
                merged_state["model"] = model_name
                payload["field_updates"]["MOTO"] = model_name
                executed_tools.append(
                    {"tool": "search_catalog", "status": "ok", "mode": "resolve_model"}
                )
                tool_call_logs.extend(model_logs)

        pending = _next_missing_after_credit(updates, state)
        payload["pending_to_resume"] = pending
        existing_model = str(state.get("model") or "").strip()
        if not existing_model:
            pending = {"type": "ask_field", "field": "MOTO"}
            payload["pending_to_resume"] = pending
            payload["request_type"] = "ask_one_missing_field"
            payload["field_name"] = "MOTO"
            payload["prompt_override"] = (
                "Listo, ya tengo tu plan. Solo dime que modelo quieres cotizar."
            )
        if pending is None and existing_model and "MOTO" not in payload["field_updates"]:
            payload["prompt_override"] = (
                f"Listo, queda como {selection_label} con plan {plan} para el modelo {existing_model}."
            )
        next_action: AdvisorAction = (
            "ask_one_missing_field"
            if not existing_model
            else
            "quote"
            if existing_model
            and pending is None
            and (
                _recent_dual_income_context(input)
                or _employment_seniority_known(state)
                or selection_key == "Nomina Tarjeta"
            )
            else "resolve_credit_plan"
        )

        return _decision(
            input=input,
            state=merged_state,
            commercial_intent="credit_option_selection",
            next_action=next_action,
            confidence=confidence,
            reasons=[
                reason_code,
                *(["resolved_plan_with_existing_model_quotes_next"] if next_action == "quote" else []),
            ],
            approved_updates=approved_updates,
            blocked_updates=blocked_updates,
            payload=payload,
            pending=pending,
            blocked_actions=blocked_action_reasons,
            executed_tools=executed_tools,
            tool_call_logs=tool_call_logs,
        )

    async def _build_negative_receipts_override_decision(
        self,
        input: SalesAdvisorDecisionInput,
        state: dict[str, Any],
        blocked_updates: list[dict[str, Any]],
    ) -> SalesAdvisorDecision:
        return await self._build_plan_override_decision(
            input=input,
            state=state,
            blocked_updates=blocked_updates,
            selection_key="Sin Comprobantes",
            selection_label="Sin Comprobantes",
            plan="20%",
            confidence=0.98,
            matched_alias="negative_receipts_signal",
            mode="negative_receipts_override",
            reason_code="negative_receipts_override_to_sin_comprobantes",
            blocked_action_reasons=[
                "no_keep_nomina_recibos_after_negative_receipts",
                "no_ask_documents_before_quote_without_model_plan",
            ],
        )

    async def _build_payroll_card_override_decision(
        self,
        input: SalesAdvisorDecisionInput,
        state: dict[str, Any],
        blocked_updates: list[dict[str, Any]],
    ) -> SalesAdvisorDecision:
        return await self._build_plan_override_decision(
            input=input,
            state=state,
            blocked_updates=blocked_updates,
            selection_key="Nomina Tarjeta",
            selection_label="Nomina Tarjeta",
            plan="10%",
            confidence=0.98,
            matched_alias="payroll_card_signal",
            mode="payroll_card_override",
            reason_code="payroll_card_override_to_nomina_tarjeta",
            blocked_action_reasons=[
                "no_ask_documents_before_quote_without_model_plan",
                "no_credit_plan_without_formal_payroll_confirmation",
            ],
        )

    async def _build_positive_receipts_override_decision(
        self,
        input: SalesAdvisorDecisionInput,
        state: dict[str, Any],
        blocked_updates: list[dict[str, Any]],
    ) -> SalesAdvisorDecision:
        return await self._build_plan_override_decision(
            input=input,
            state=state,
            blocked_updates=blocked_updates,
            selection_key="Nomina Recibos",
            selection_label="Nomina Recibos",
            plan="15%",
            confidence=0.98,
            matched_alias="positive_receipts_signal",
            mode="positive_receipts_override",
            reason_code="positive_receipts_override_to_nomina_recibos",
            blocked_action_reasons=[
                "no_ask_documents_before_quote_without_model_plan",
                "no_fallback_to_generic_credit_when_receipts_are_explicit",
            ],
        )

    async def _build_guardia_override_decision(
        self,
        input: SalesAdvisorDecisionInput,
        state: dict[str, Any],
        blocked_updates: list[dict[str, Any]],
    ) -> SalesAdvisorDecision:
        return await self._build_plan_override_decision(
            input=input,
            state=state,
            blocked_updates=blocked_updates,
            selection_key="Guardia de Seguridad",
            selection_label="Guardia",
            plan="30%",
            confidence=0.97,
            matched_alias="guardia_signal",
            mode="guardia_override",
            reason_code="guardia_priority_overrides_generic_flow",
            blocked_action_reasons=[
                "no_fallback_to_sin_comprobantes_before_guardia",
                "no_ask_documents_before_quote_without_model_plan",
            ],
        )

    async def _negative_receipts_plan_correction_decision(
        self,
        input: SalesAdvisorDecisionInput,
        state: dict[str, Any],
        blocked_updates: list[dict[str, Any]],
    ) -> SalesAdvisorDecision | None:
        if not _negative_receipts_signal(input.inbound_text):
            return None
        if str(state.get("income_type") or "").strip() != "Nomina Recibos":
            return None
        return await self._build_negative_receipts_override_decision(
            input,
            state,
            blocked_updates,
        )

    async def _early_model_change_decision(
        self,
        input: SalesAdvisorDecisionInput,
        state: dict[str, Any],
        blocked_updates: list[dict[str, Any]],
    ) -> SalesAdvisorDecision | None:
        if state.get("income_type") or not _early_model_change_signal(input):
            return None
        model_result = await self._resolve_model(input, allow_credit_interest=True)
        if model_result is None:
            return None
        model_name, model_payload, logs = model_result
        return _decision(
            input=input,
            state={**state, "credit_intent": True, "model": model_name},
            commercial_intent="model_change",
            next_action="ask_income_type",
            confidence=0.94,
            reasons=["early_model_change_preserves_pending_credit_question"],
            approved_updates={"MOTO": model_name},
            blocked_updates=blocked_updates,
            payload={
                "status": "ok",
                "request_type": "ask_income_type",
                "field_name": getattr(input.pipeline, "document_requirements_field", "CREDITO"),
                "options": _credit_options(input.pipeline),
                "prompt_override": (
                    f"Va, la cambiamos a {model_name}. "
                    "Para seguir con el credito, dime como recibes tus ingresos."
                ),
                "resolved_model": model_payload,
            },
            blocked_actions=[
                "no_reset_credit_flow_after_model_change",
                "no_ask_model_already_resolved",
                "no_ask_documents_before_quote_without_model_plan",
            ],
            executed_tools=[{"tool": "search_catalog", "status": "ok", "mode": "resolve_model"}],
            tool_call_logs=logs,
        )

    def _income_disambiguation_decision(
        self,
        input: SalesAdvisorDecisionInput,
        state: dict[str, Any],
        blocked_updates: list[dict[str, Any]],
        *,
        signals: IncomeDisambiguationSignals,
        topic: str = "income_clarification",
        answer_topic: str = "income_clarification",
        pending_field: str = "CREDITO",
        reasons: list[str] | None = None,
    ) -> SalesAdvisorDecision:
        pending = {"type": "ask_field", "field": pending_field}
        answer = _income_disambiguation_answer(signals, inbound_text=input.inbound_text)
        payload = {
            "status": "ok",
            "request_type": "requirements_answer_only" if topic == "requirements" else "income_disambiguation",
            "topic": answer_topic,
            "answer": answer,
            "answers": [
                {
                    "topic": answer_topic,
                    "answer": answer,
                    "source": "sales_policy_income_disambiguation",
                    "confidence": 1.0,
                }
            ],
            "answered_intents": [topic, answer_topic] if topic != answer_topic else [topic],
            "resume_pending_action": pending,
            "next_required_step": pending,
            "policy_trace": {
                "income_ambiguity": signals.income_ambiguity,
                "payroll_ambiguous": signals.payroll_ambiguous,
                "deposit_ambiguous": signals.deposit_ambiguous,
                "dual_income_detected": signals.dual_income_detected,
                "needs_income_disambiguation": signals.needs_income_disambiguation,
                "credit_plan_write_blocked_reason": signals.credit_plan_write_blocked_reason,
                "dual_income_resolution_required": signals.dual_income_detected,
                "selected_income_source": None,
                "selected_income_source_confidence": 0.0,
                "documents_blocked_by_dual_income": signals.dual_income_detected,
                "quote_blocked_by_dual_income": signals.dual_income_detected,
                "pending_flow_forced_to_income_disambiguation": signals.needs_income_disambiguation,
            },
            "dual_income_resolution_required": signals.dual_income_detected,
            "selected_income_source": None,
            "selected_income_source_confidence": 0.0,
            "documents_blocked_by_dual_income": signals.dual_income_detected,
            "quote_blocked_by_dual_income": signals.dual_income_detected,
            "pending_flow_forced_to_income_disambiguation": signals.needs_income_disambiguation,
        }
        return _decision(
            input=input,
            state=state,
            commercial_intent="income_disambiguation",
            next_action="answer_faq_and_resume",
            confidence=0.92,
            reasons=reasons or ["income_ambiguity_requires_clarification_before_plan"],
            blocked_updates=_direct_question_blocked_updates(
                input,
                blocked_updates,
                "income_ambiguity_requires_clarification_before_plan",
            ),
            payload=payload,
            pending=pending,
            blocked_actions=[
                "no_write_credit_plan_without_income_disambiguation",
                "no_write_down_payment_without_income_disambiguation",
                "no_ask_documents_before_quote_without_model_plan",
            ],
        )

    def _plan_restate_needs_model_decision(
        self,
        input: SalesAdvisorDecisionInput,
        state: dict[str, Any],
        blocked_updates: list[dict[str, Any]],
    ) -> SalesAdvisorDecision | None:
        if not state.get("income_type") or not state.get("plan") or state.get("model"):
            return None
        if _document_signal(input) or _is_requirements_question(input):
            return None
        if _has_model_resolution_signal(
            text=input.inbound_text,
            allow_credit_interest=True,
            existing_model=False,
        ):
            return None
        parsed_seniority = parse_employment_seniority(input.inbound_text)
        if parsed_seniority is None and not _has_down_payment_signal(input.inbound_text):
            return None

        approved_updates: dict[str, Any] = {}
        if parsed_seniority is not None:
            approved_updates.update(_seniority_updates(parsed_seniority))

        payload = {
            "status": "ok",
            "type": "credit_plan_resolution",
            "input": input.inbound_text,
            "field_name": getattr(input.pipeline, "document_requirements_field", "CREDITO"),
            "selection_key": state.get("income_type"),
            "selection_label": state.get("income_type"),
            "matched_alias": "existing_plan_context",
            "confidence": 0.9,
            "field_updates": {
                "CREDITO": state.get("income_type"),
                "ENGANCHE": state.get("plan"),
            },
            "source": {
                "tool": "resolve_credit_plan",
                "mode": "existing_plan_context",
            },
        }
        if parsed_seniority is not None or _has_down_payment_signal(input.inbound_text):
            seniority_hint = (
                f"Con {parsed_seniority.display_value}, "
                if parsed_seniority is not None
                else ""
            )
            payload["prompt_override"] = (
                f"Va, {seniority_hint}tu plan queda como {state.get('income_type')} con "
                f"{state.get('plan')} de enganche. Para cotizarte bien dime que modelo quieres revisar."
            )
        pending = {"type": "ask_field", "field": "MOTO", "alternatives": ["modelo", "categoria"]}
        payload["pending_to_resume"] = pending

        next_state = dict(state)
        if parsed_seniority is not None:
            next_state["employment_seniority"] = parsed_seniority.display_value

        return _decision(
            input=input,
            state=next_state,
            commercial_intent="credit_option_selection",
            next_action="resolve_credit_plan",
            confidence=0.9,
            reasons=["existing_plan_context_requires_model_before_quote"],
            approved_updates=approved_updates,
            blocked_updates=blocked_updates,
            payload=payload,
            pending=pending,
            blocked_actions=[
                "no_quote_without_model_and_plan",
                "no_ask_documents_before_quote_without_model_plan",
            ],
            executed_tools=[{"tool": "resolve_credit_plan", "status": "ok", "mode": "existing_plan_context"}],
            tool_call_logs=[
                _tool_log(
                    "resolve_credit_plan",
                    {"input_text": input.inbound_text, "mode": "existing_plan_context"},
                    payload,
                    0,
                )
            ],
        )


def _decision(
    *,
    input: SalesAdvisorDecisionInput,
    state: dict[str, Any],
    commercial_intent: str,
    next_action: AdvisorAction,
    confidence: float,
    reasons: list[str],
    approved_updates: dict[str, Any] | None = None,
    blocked_updates: list[dict[str, Any]] | None = None,
    payload: dict[str, Any] | None = None,
    pending: dict[str, Any] | None = None,
    blocked_actions: list[str] | str | None = None,
    faq_tool_used: bool = False,
    catalog_category: str | None = None,
    catalog_browse_intent: str | None = None,
    executed_tools: list[dict[str, Any]] | None = None,
    tool_call_logs: list[dict[str, Any]] | None = None,
    should_override: bool = True,
) -> SalesAdvisorDecision:
    normalized_updates = dict(approved_updates or {})
    normalized_payload = dict(payload or {})
    consistency_errors: list[dict[str, Any]] = []
    if normalized_updates and {"CREDITO", "ENGANCHE"} & set(normalized_updates):
        coherent_credit, coherent_plan, consistency_errors = enforce_credit_plan_invariants(
            normalized_updates.get("CREDITO", state.get("income_type")),
            normalized_updates.get("ENGANCHE", state.get("plan")),
        )
        if coherent_credit:
            normalized_updates["CREDITO"] = coherent_credit
            normalized_payload["selection_key"] = coherent_credit
            normalized_payload.setdefault("selection_label", coherent_credit)
        if coherent_plan:
            normalized_updates["ENGANCHE"] = coherent_plan
            normalized_payload["down_payment"] = coherent_plan
        field_updates = dict(normalized_payload.get("field_updates") or {})
        if coherent_credit:
            field_updates["CREDITO"] = coherent_credit
        if coherent_plan:
            field_updates["ENGANCHE"] = coherent_plan
        if field_updates:
            normalized_payload["field_updates"] = field_updates
        if consistency_errors:
            normalized_payload["state_consistency_errors"] = consistency_errors
    if isinstance(blocked_actions, str):
        blocked = [blocked_actions]
    else:
        blocked = list(blocked_actions or [])
    runtime_action = _RUNTIME_ACTION_BY_ADVISOR[next_action]
    return SalesAdvisorDecision(
        commercial_intent=commercial_intent,
        next_action=next_action,
        runtime_action=runtime_action,
        confidence=confidence,
        reason_codes=reasons,
        field_updates_approved=normalized_updates,
        field_updates_blocked=blocked_updates or [],
        tool_payload=normalized_payload,
        pending_to_resume=pending,
        blocked_commercial_actions=_dedupe(
            [
                *blocked,
                *_standard_blocks(input=input, state=state, next_action=next_action),
            ]
        ),
        commercial_state=state,
        faq_tool_used=faq_tool_used,
        catalog_category=catalog_category,
        catalog_browse_intent=catalog_browse_intent,
        executed_tools=executed_tools or [],
        tool_call_logs=tool_call_logs or [],
        state_consistency_errors=consistency_errors,
        should_override_runtime_action=should_override,
    )


def _confirmation_resume_decision(
    input: SalesAdvisorDecisionInput,
    state: dict[str, Any],
    blocked_updates: list[dict[str, Any]],
) -> SalesAdvisorDecision | None:
    if not input.metadata.get("pending_confirmation_resolved"):
        return None
    if state.get("model") and state.get("plan"):
        return _decision(
            input=input,
            state=state,
            commercial_intent="confirmation_resolved",
            next_action="quote",
            confidence=0.88,
            reasons=["pending_confirmation_resolved_quote_ready"],
            blocked_updates=blocked_updates,
            blocked_actions=[
                "no_ask_model_already_resolved",
                "no_ask_documents_before_quote_without_model_plan",
            ],
        )
    if state.get("model") and not state.get("income_type"):
        return _decision(
            input=input,
            state=state,
            commercial_intent="confirmation_resolved",
            next_action="ask_income_type",
            confidence=0.76,
            reasons=["pending_confirmation_resolved_income_type_missing"],
            blocked_updates=blocked_updates,
                payload={
                    "status": "ok",
                    "request_type": "ask_income_type",
                    "active_purchase_mode": "credit",
                    "quote_mode": "credit",
                    "field_name": getattr(input.pipeline, "document_requirements_field", "CREDITO"),
                    "options": _credit_options(input.pipeline),
                },
        )
    missing_field = "MOTO" if not state.get("model") else "ENGANCHE"
    return _decision(
        input=input,
        state=state,
        commercial_intent="confirmation_resolved",
        next_action="ask_one_missing_field",
        confidence=0.7,
        reasons=["pending_confirmation_resolved_but_quote_fields_missing"],
        blocked_updates=blocked_updates,
        payload={
            "status": "ok",
            "request_type": "ask_one_missing_field",
            "field_name": missing_field,
            "prompt_override": (
                f"Va, con tu plan de {state.get('income_type')} si aplica {state.get('plan')}. "
                "Dime que modelo quieres cotizar."
                if missing_field == "MOTO" and state.get("income_type") and state.get("plan")
                else None
            ),
        },
    )


def _resolved_plan_needs_model_decision(
    input: SalesAdvisorDecisionInput,
    state: dict[str, Any],
    blocked_updates: list[dict[str, Any]],
) -> SalesAdvisorDecision | None:
    if state.get("income_type") != "Nomina Tarjeta" or str(state.get("plan") or "") != "10%":
        return None
    if state.get("model"):
        return None
    if not _is_payroll_receipts_confirmation_reply(input.inbound_text):
        return None
    return _decision(
        input=input,
        state=state,
        commercial_intent="credit_plan_confirmed_needs_model",
        next_action="ask_one_missing_field",
        confidence=0.86,
        reasons=["payroll_receipts_confirmed_model_required_before_quote"],
        blocked_updates=blocked_updates,
        payload={
            "status": "ok",
            "request_type": "ask_one_missing_field",
            "field_name": "MOTO",
            "prompt_override": (
                "Va, con tu plan de Nomina Tarjeta si aplica 10%. "
                "Dime que modelo quieres cotizar."
            ),
        },
        blocked_actions=[
            "no_quote_without_model_and_plan",
            "no_ask_documents_before_quote_without_model_plan",
        ],
    )


def _employment_seniority_decision(
    input: SalesAdvisorDecisionInput,
    state: dict[str, Any],
    blocked_updates: list[dict[str, Any]],
) -> SalesAdvisorDecision | None:
    if not _employment_seniority_context_ready(state):
        return None

    parsed_seniority = parse_employment_seniority(input.inbound_text)
    if parsed_seniority is not None:
        return _employment_seniority_continue_decision(
            input=input,
            state={**state, "employment_seniority": parsed_seniority.display_value},
            blocked_updates=blocked_updates,
            approved_updates=_seniority_updates(parsed_seniority),
            reason=(
                "employment_seniority_corrected"
                if state.get("employment_seniority")
                else "employment_seniority_duration_recorded"
            ),
        )

    if _employment_seniority_known(state) and _is_employment_seniority_followup(input):
        return _employment_seniority_continue_decision(
            input=input,
            state=state,
            blocked_updates=blocked_updates,
            approved_updates={},
            reason="employment_seniority_already_present_continue",
        )

    if (
        not _employment_seniority_known(state)
        and _is_employment_seniority_followup(input)
        and not is_valid_seniority_duration(input.inbound_text)
    ):
        return _decision(
            input=input,
            state=state,
            commercial_intent="employment_seniority_missing",
            next_action="ask_one_missing_field",
            confidence=0.86,
            reasons=["employment_seniority_required_before_documents"],
            blocked_updates=blocked_updates,
            payload={
                "status": "ok",
                "request_type": "ask_employment_seniority",
                "field_name": ANTIGUEDAD_LABORAL_FIELD_KEY,
                "field_description": "Antiguedad laboral",
            },
            pending={"type": "ask_field", "field": ANTIGUEDAD_LABORAL_FIELD_KEY},
            blocked_actions=[
                "no_documents_before_employment_seniority",
                "no_quote_for_credit_followup_without_seniority",
            ],
        )
    return None


def _employment_seniority_to_income_type_decision(
    input: SalesAdvisorDecisionInput,
    state: dict[str, Any],
    blocked_updates: list[dict[str, Any]],
) -> SalesAdvisorDecision | None:
    if not state.get("model") or state.get("income_type"):
        return None
    parsed_seniority = parse_employment_seniority(input.inbound_text)
    if parsed_seniority is None:
        return None
    return _decision(
        input=input,
        state={**state, "employment_seniority": parsed_seniority.display_value},
        commercial_intent="employment_seniority_recorded",
        next_action="ask_income_type",
        confidence=0.9,
        reasons=["employment_seniority_duration_recorded_before_income_type"],
        approved_updates=_seniority_updates(parsed_seniority),
        blocked_updates=blocked_updates,
        payload={
            "status": "ok",
            "request_type": "ask_income_type",
            "field_name": getattr(input.pipeline, "document_requirements_field", "CREDITO"),
            "options": _credit_options(input.pipeline),
            "acknowledged_employment_seniority": parsed_seniority.display_value,
        },
        blocked_actions=[
            "no_quote_before_income_type_after_seniority",
            "no_documents_before_income_type_after_seniority",
        ],
    )


def _employment_seniority_continue_decision(
    *,
    input: SalesAdvisorDecisionInput,
    state: dict[str, Any],
    blocked_updates: list[dict[str, Any]],
    approved_updates: dict[str, Any],
    reason: str,
) -> SalesAdvisorDecision:
    payload: dict[str, Any] = {
        "status": "ok",
        "request_type": "ask_missing_document",
    }
    extracted = dict(input.extracted_data or {})
    for key, value in approved_updates.items():
        extracted[key] = {"value": value, "confidence": 1.0, "source_turn": 0}
    result = get_missing_documents(
        pipeline=input.pipeline,
        state={"extracted_data": extracted},
    )
    pending: dict[str, Any] | None = None
    if not isinstance(result, ToolNoDataResult):
        payload["requirements"] = result.model_dump(mode="json")
        pending = _pending_from_missing_documents(result)
        payload["pending_to_resume"] = pending
    return _decision(
        input=input,
        state=state,
        commercial_intent="employment_seniority_recorded",
        next_action="ask_missing_document",
        confidence=0.88,
        reasons=[reason, "no_filtro_derivation_without_configured_threshold"],
        approved_updates=approved_updates,
        blocked_updates=blocked_updates,
        payload=payload,
        pending=pending,
        blocked_actions=[
            "no_quote_after_employment_seniority_update",
            "no_filtro_derivation_without_configured_threshold",
        ],
        executed_tools=[{"tool": "getMissingDocuments", "status": payload.get("status")}],
        tool_call_logs=[
            _tool_log(
                "getMissingDocuments",
                {"source": "employment_seniority"},
                payload,
                0,
            )
        ],
    )


def _document_claim_clarification_decision(
    input: SalesAdvisorDecisionInput,
    state: dict[str, Any],
    blocked_updates: list[dict[str, Any]],
) -> SalesAdvisorDecision:
    pending = _pending_from_requirements(input, state)
    return _decision(
        input=input,
        state=state,
        commercial_intent="documents_text_claim",
        next_action="clarify_ambiguous_yes_no",
        confidence=0.72,
        reasons=["text_document_claim_without_attachment_or_vision_write"],
        blocked_updates=blocked_updates,
        payload={
            "status": "ok",
            "request_type": "clarify_ambiguous_yes_no",
            "clarification_type": "document_claim",
            "pending_to_resume": pending,
            "suggested_clarification": "Me confirmas a que te refieres para revisar que falta?",
        },
        pending=pending,
        blocked_actions=[
            "no_documents_as_purchase_intent",
            "no_mark_document_received_without_attachment",
        ],
    )


def _text_document_claim_without_evidence_decision(
    input: SalesAdvisorDecisionInput,
    state: dict[str, Any],
    blocked_updates: list[dict[str, Any]],
) -> SalesAdvisorDecision | None:
    if not _is_text_document_claim_without_evidence(input, state):
        return None
    pending = _pending_from_requirements(input, state)
    answer = (
        "Todavia no me aparece cargado en el expediente. "
        "Cuando me mandes la foto o el archivo lo reviso."
    )
    return _decision(
        input=input,
        state=state,
        commercial_intent="documents_text_claim_without_evidence",
        next_action="answer_faq_and_resume",
        confidence=0.86,
        reasons=["text_document_claim_requires_attachment_before_review"],
        blocked_updates=_direct_question_blocked_updates(
            input,
            blocked_updates,
            "text_document_claim_without_attachment_does_not_update_documents",
        ),
        payload={
            "status": "ok",
            "answer": answer,
            "answered_intents": ["documents"],
            "detected_intents": ["documents"],
            "intent_stack": ["documents"],
            "resume_pending_action": pending,
            "next_required_step": pending,
            "source": {
                "type": "document_claim_without_upload",
            },
        },
        pending=pending,
        blocked_actions=[
            "no_mark_document_received_without_attachment",
            "no_quote_from_text_document_claim",
        ],
    )


def _documents_submission_confirmation_decision(
    input: SalesAdvisorDecisionInput,
    state: dict[str, Any],
    blocked_updates: list[dict[str, Any]],
) -> SalesAdvisorDecision | None:
    if not _is_documents_submission_confirmation(input, state):
        return None
    pending = _pending_from_requirements(input, state)
    payload: dict[str, Any] = {
        "status": "ok",
        "request_type": "ask_missing_document",
        "pending_to_resume": pending,
    }
    result = get_missing_documents(
        pipeline=input.pipeline,
        state={"extracted_data": input.extracted_data},
    )
    if not isinstance(result, ToolNoDataResult):
        payload["requirements"] = result.model_dump(mode="json")
        if pending is None:
            pending = _pending_from_missing_documents(result)
            payload["pending_to_resume"] = pending
    return _decision(
        input=input,
        state=state,
        commercial_intent="documents_submitted_confirmation",
        next_action="ask_missing_document",
        confidence=0.88,
        reasons=["document_submission_confirmation_prioritized_over_quote"],
        blocked_updates=blocked_updates,
        payload=payload,
        pending=pending,
        blocked_actions=[
            "no_quote_during_document_review_without_explicit_change_request",
            "no_recompute_quote_from_document_submission_confirmation",
        ],
        executed_tools=[{"tool": "getMissingDocuments", "status": payload.get("status")}],
        tool_call_logs=[
            _tool_log(
                "getMissingDocuments",
                {"source": "documents_submission_confirmation"},
                payload,
                0,
            )
        ],
    )


def resolve_acknowledgement_context(
    *,
    ack_class: str,
    last_bot_question: str | None,
    current_stage: str,
    contact_fields: dict[str, Any],
    last_quote_signature: str | None,
    pending_field: str | None,
    documents_state: dict[str, Any] | None,
) -> AcknowledgementContextResolution | None:
    if ack_class in {
        "insufficient_answer_to_concrete_question",
        "nonsense_clarification",
    }:
        return AcknowledgementContextResolution(
            advisor_action="clarify_ambiguous_yes_no",
            runtime_action="ask_clarification",
            commercial_intent=ack_class,
            reason=ack_class,
            forbidden_actions_applied=[
                "no_write_critical_fields_from_acknowledgement",
                "no_quote_from_ambiguous_acknowledgement",
                "no_auto_ask_field_from_nonsense",
            ],
        )
    if ack_class != "soft_close":
        return None

    income_type = str(contact_fields.get("CREDITO") or "").strip()
    plan = str(contact_fields.get("ENGANCHE") or "").strip()
    model = str(contact_fields.get("MOTO") or "").strip()
    employment_seniority = str(contact_fields.get(ANTIGUEDAD_LABORAL_FIELD_KEY) or "").strip()
    seniority_known = bool(employment_seniority or contact_fields.get("FILTRO"))
    stage = _normalize(current_stage)
    last_bot_norm = _normalize(last_bot_question or "")
    document_kind = str((documents_state or {}).get("kind") or "").strip()
    missing_documents = [
        str(item)
        for item in ((documents_state or {}).get("missing") or [])
        if str(item).strip()
    ]

    if document_kind == "missing_documents":
        humanized_missing = humanize_document_labels(missing_documents)
        if plan and not model:
            return AcknowledgementContextResolution(
                advisor_action="ask_one_missing_field",
                runtime_action="ask_field",
                commercial_intent="soft_close_resume_model_before_documents",
                reason="soft_close_prioritizes_model_before_documents",
                forbidden_actions_applied=[
                    "no_quote_without_model_and_plan",
                    "no_documents_before_quote_without_model_plan",
                    "no_model_invention_from_soft_close",
                ],
                payload={
                    "status": "ok",
                    "request_type": "ask_field",
                    "field_name": "MOTO",
                    "prompt_override": (
                        "Va, antes de pedirte documentos solo me falta el modelo exacto para decirte precio y enganche."
                    ),
                },
                pending_to_resume={"type": "ask_field", "field": "MOTO"},
                confidence=0.88,
            )
        return AcknowledgementContextResolution(
            advisor_action="soft_close",
            runtime_action="soft_close",
            commercial_intent="soft_close_document_pending",
            reason="soft_close_acknowledges_missing_documents_without_repeating_prompt",
            forbidden_actions_applied=[
                "no_quote_from_soft_close",
                "no_catalog_from_soft_close",
                "no_faq_from_soft_close",
            ],
            payload={
                "status": "ok",
                "request_type": "soft_close",
                "suggested_response": (
                    "Va, aqui quedo al pendiente. Cuando tengas "
                    + join_humanized_documents(humanized_missing)
                    + " me lo mandas y lo reviso."
                    if humanized_missing
                    else "Va, aqui quedo al pendiente. Cuando tengas los documentos me los mandas y lo reviso."
                ),
            },
            confidence=0.86,
        )

    if document_kind == "requirements_complete" and stage:
        return AcknowledgementContextResolution(
            advisor_action="soft_close",
            runtime_action="soft_close",
            commercial_intent="soft_close_documents_complete",
            reason="soft_close_after_documents_complete",
            forbidden_actions_applied=[
                "no_quote_from_soft_close",
                "no_documents_relist_after_complete_file",
            ],
            payload={
                "status": "ok",
                "request_type": "soft_close",
                "suggested_response": (
                    "Perfecto, ya quedo la papeleria. El siguiente paso es revisarlo con el equipo."
                ),
            },
            confidence=0.8,
        )

    if pending_field == ANTIGUEDAD_LABORAL_FIELD_KEY and not seniority_known:
        return AcknowledgementContextResolution(
            advisor_action="ask_one_missing_field",
            runtime_action="ask_field",
            commercial_intent="soft_close_resume_employment_seniority",
            reason="soft_close_resumes_employment_seniority",
            forbidden_actions_applied=[
                "no_quote_from_soft_close",
                "no_documents_before_employment_seniority",
            ],
            payload={
                "status": "ok",
                "request_type": "ask_employment_seniority",
                "field_name": ANTIGUEDAD_LABORAL_FIELD_KEY,
                "field_description": "Antiguedad laboral",
                "prompt_override": "Va, para seguir solo me falta saber cuanto tiempo llevas en tu empleo actual.",
            },
            pending_to_resume={"type": "ask_field", "field": ANTIGUEDAD_LABORAL_FIELD_KEY},
            confidence=0.86,
        )

    if not income_type or pending_field == "CREDITO":
        return AcknowledgementContextResolution(
            advisor_action="ask_income_type",
            runtime_action="ask_credit_context",
            commercial_intent="soft_close_resume_income_type",
            reason="soft_close_resumes_income_type",
            forbidden_actions_applied=[
                "no_quote_from_soft_close",
                "no_documents_before_credit_context",
                "no_handoff_from_soft_close_without_explicit_request",
            ],
            payload={
                "status": "ok",
                "request_type": "ask_income_type",
                "field_name": "CREDITO",
                "options": [],
                "prompt_override": "Va, para orientarte bien dime como recibes tus ingresos.",
            },
            confidence=0.86,
        )

    if (plan and not model) or pending_field == "MOTO":
        return AcknowledgementContextResolution(
            advisor_action="ask_one_missing_field",
            runtime_action="ask_field",
            commercial_intent="soft_close_resume_model",
            reason="soft_close_resumes_model",
            forbidden_actions_applied=[
                "no_quote_without_model_and_plan",
                "no_model_invention_from_soft_close",
                "no_documents_before_quote_without_model_plan",
            ],
            payload={
                "status": "ok",
                "request_type": "ask_one_missing_field",
                "field_name": "MOTO",
                "prompt_override": "Perfecto, dime que modelo quieres cotizar.",
            },
            pending_to_resume={"type": "ask_field", "field": "MOTO"},
            confidence=0.88,
        )

    if last_quote_signature:
        return AcknowledgementContextResolution(
            advisor_action="soft_close",
            runtime_action="soft_close",
            commercial_intent="soft_close_after_quote",
            reason="soft_close_after_active_quote",
            forbidden_actions_applied=[
                "no_quote_from_soft_close",
                "no_requote_without_signature_change",
                "no_handoff_from_soft_close_without_explicit_request",
            ],
            payload={
                "status": "ok",
                "request_type": "soft_close",
                "suggested_response": (
                    "Claro, revisalo con calma. Si quieres avanzar, te digo que documentos ocupariamos."
                ),
            },
            confidence=0.88,
        )

    if income_type and plan and model and (
        "document" in last_bot_norm or "papel" in last_bot_norm or "falt" in last_bot_norm
    ):
        return AcknowledgementContextResolution(
            advisor_action="ask_missing_document",
            runtime_action="classify_document",
            commercial_intent="soft_close_resume_documents",
            reason="soft_close_resumes_document_context",
            forbidden_actions_applied=[
                "no_quote_from_soft_close",
                "no_catalog_from_soft_close",
            ],
            payload={
                "status": "ok",
                "request_type": "ask_missing_document",
                "prompt_override": "Va, si quieres avanzar te digo que documentos ocupariamos para tu plan.",
            },
            confidence=0.8,
        )

    return AcknowledgementContextResolution(
        advisor_action="soft_close",
        runtime_action="soft_close",
        commercial_intent="soft_close_contextual",
        reason="soft_close_without_state_change",
        forbidden_actions_applied=[
            "no_quote_from_soft_close",
            "no_state_write_from_acknowledgement",
        ],
        payload={
            "status": "ok",
            "request_type": "soft_close",
            "suggested_response": (
                "Claro, revisalo con calma. Cuando quieras seguimos desde aqui."
            ),
        },
        confidence=0.76,
    )


def _vague_model_reference_decision(
    input: SalesAdvisorDecisionInput,
    state: dict[str, Any],
    blocked_updates: list[dict[str, Any]],
) -> SalesAdvisorDecision:
    return _decision(
        input=input,
        state=state,
        commercial_intent="unresolved_reference",
        next_action="clarify_ambiguous_yes_no",
        confidence=0.82,
        reasons=["vague_model_reference_requires_name_link_or_model"],
        blocked_updates=_direct_question_blocked_updates(
            input,
            blocked_updates,
            "vague_reference_does_not_update_model",
        ),
        payload={
            "status": "ok",
            "request_type": "clarify_ambiguous_yes_no",
            "clarification_type": "model_reference",
            "suggested_clarification": (
                "Me compartes el nombre, link o modelo de la moto para ubicarla?"
            ),
        },
        blocked_actions=[
            "no_write_moto_without_model_evidence",
            "no_quote_without_model_and_plan",
            "no_ask_documents_before_quote_without_model_plan",
        ],
    )


def _missing_model_for_quote_decision(
    input: SalesAdvisorDecisionInput,
    state: dict[str, Any],
    blocked_updates: list[dict[str, Any]],
) -> SalesAdvisorDecision:
    return _decision(
        input=input,
        state=state,
        commercial_intent="quote_missing_model",
        next_action="ask_one_missing_field",
        confidence=0.78,
        reasons=["quote_requested_but_model_missing"],
        blocked_updates=_direct_question_blocked_updates(
            input,
            blocked_updates,
            "quote_request_without_model_does_not_update_state",
        ),
        payload={
            "status": "ok",
            "request_type": "ask_field",
            "field_name": "MOTO",
            "prompt_override": (
                "Te entiendo. Para decirte precio y enganche solo me falta el modelo exacto de la moto."
            ),
        },
        blocked_actions=[
            "no_quote_without_model_and_plan",
            "no_write_moto_without_model_evidence",
            "no_ask_documents_before_quote_without_model_plan",
        ],
    )


def _missing_model_for_cash_price_decision(
    input: SalesAdvisorDecisionInput,
    state: dict[str, Any],
    blocked_updates: list[dict[str, Any]],
) -> SalesAdvisorDecision:
    cash_state = {**state, "active_purchase_mode": "cash", "quote_mode": "cash"}
    return _decision(
        input=input,
        state=cash_state,
        commercial_intent="cash_price_missing_model",
        next_action="ask_one_missing_field",
        confidence=0.86,
        reasons=["cash_price_requested_but_model_missing"],
        blocked_updates=_direct_question_blocked_updates(
            input,
            blocked_updates,
            "cash_price_request_without_model_does_not_update_credit_fields",
        ),
        payload={
            "status": "ok",
            "request_type": "ask_field",
            "field_name": "MOTO",
            "quote_mode": "cash",
            "active_purchase_mode": "cash",
            "prompt_override": "Para decirte el precio de contado solo me falta el modelo.",
        },
        blocked_actions=[
            "cash_mode_blocks_credit_flow",
            "no_ask_credit_context_for_cash_price",
            "no_ask_documents_for_cash_price",
            "no_write_moto_without_model_evidence",
        ],
    )


def _last_quote_message(input: SalesAdvisorDecisionInput) -> str | None:
    for direction, text in reversed(_recent_history(input)[-8:]):
        if _normalize(str(direction or "")) not in {"assistant", "bot", "outbound", "system"}:
            continue
        candidate = str(text or "").strip()
        normalized = _normalize(candidate)
        if "$" in candidate and any(
            marker in normalized for marker in ("enganche", "quincenal", "contado", "plazo")
        ):
            return candidate
    return None


def _documents_quote_context(
    input: SalesAdvisorDecisionInput,
    state: dict[str, Any],
) -> dict[str, Any]:
    missing_fields: list[str] = []
    if not state.get("income_type"):
        missing_fields.append("CREDITO")
    if not state.get("plan"):
        missing_fields.append("ENGANCHE")
    if not state.get("model"):
        missing_fields.append("MOTO")
    quote_context_ready = not missing_fields
    last_quote_message = _last_quote_message(input)
    last_bot_norm = _normalize(_last_bot_message(input) or "")
    document_progress_active = _has_document_progress(input) or any(
        term in last_bot_norm for term in ("document", "papel", "falt", "ine", "comprobante")
    )
    normalized_quote = _normalize(last_quote_message or "")
    normalized_model = _normalize(str(state.get("model") or ""))
    normalized_plan = _normalize(str(state.get("plan") or ""))
    quote_matches_current_context = bool(
        quote_context_ready
        and normalized_quote
        and normalized_model
        and normalized_model in normalized_quote
        and (not normalized_plan or normalized_plan in normalized_quote)
    )
    quote_required = bool(
        quote_context_ready
        and not document_progress_active
        and (
            _explicit_quote_request(input)
            or _is_quote_or_price_complaint(input.inbound_text)
            or not quote_matches_current_context
        )
    )
    blocked_reason = None
    if missing_fields:
        blocked_reason = "quote_context_missing_fields"
    elif quote_required and not last_quote_message:
        blocked_reason = "quote_required_before_documents"
    elif quote_required and not quote_matches_current_context:
        blocked_reason = "model_change_requires_requote_before_documents"
    return {
        "quote_context_ready": quote_context_ready,
        "quote_context_missing_fields": missing_fields,
        "quote_required_before_documents": quote_required,
        "quote_matches_current_context": quote_matches_current_context,
        "documents_blocked_reason": blocked_reason,
    }


def _requirements_answer_only_text(
    *,
    blocked_reason: str,
    signals: IncomeDisambiguationSignals | None = None,
) -> str:
    if signals is not None and signals.needs_income_disambiguation:
        if signals.dual_income_detected:
            return (
                "Los documentos exactos dependen de cual ingreso vas a usar. "
                + _income_disambiguation_answer(signals)
            )
        return (
            "Los documentos exactos dependen de como compruebes ingresos. "
            + _income_disambiguation_answer(signals)
        )
    if blocked_reason == "requirements_need_model_context":
        return "Eso te lo aterrizo bien ya que tengamos el modelo y el plan que vamos a cotizar."
    if blocked_reason == "quote_required_before_documents":
        return "Primero conviene dejar cerrada la cotizacion del modelo y plan para decirte los documentos exactos."
    return "Los documentos exactos dependen de como compruebes ingresos y del plan que te corresponda."


def _requirements_policy_trace(
    *,
    blocked_reason: str,
    quote_context: dict[str, Any],
    pending: dict[str, Any] | None,
    signals: IncomeDisambiguationSignals | None = None,
) -> dict[str, Any]:
    return {
        "quote_required_before_documents": bool(quote_context.get("quote_required_before_documents")),
        "documents_blocked_reason": blocked_reason,
        "requirements_answer_only": pending is not None,
        "pending_flow_demoted_reason": blocked_reason if pending is not None else None,
        "quote_context_ready": bool(quote_context.get("quote_context_ready")),
        "quote_context_missing_fields": list(quote_context.get("quote_context_missing_fields") or []),
        "formal_documents_blocked_until_income_resolved": bool(
            signals is not None and signals.needs_income_disambiguation
        )
        or blocked_reason == "requirements_need_credit_context",
        "income_ambiguity": bool(signals and signals.income_ambiguity),
        "payroll_ambiguous": bool(signals and signals.payroll_ambiguous),
        "deposit_ambiguous": bool(signals and signals.deposit_ambiguous),
        "dual_income_detected": bool(signals and signals.dual_income_detected),
        "needs_income_disambiguation": bool(signals and signals.needs_income_disambiguation),
        "credit_plan_write_blocked_reason": (
            signals.credit_plan_write_blocked_reason if signals is not None else None
        ),
    }


def _commercial_state(input: SalesAdvisorDecisionInput) -> dict[str, Any]:
    values = _flat_values(input.extracted_data)
    income_type = values.get(getattr(input.pipeline, "document_requirements_field", "CREDITO"))
    if _generic_credit_value(income_type):
        income_type = None
    plan = values.get("ENGANCHE") or values.get("PLAN") or values.get("plan")
    model = values.get("MOTO")
    if _generic_model_value(model):
        model = None
    state = {
        "credit_intent": _is_credit_interest(input),
        "income_type": income_type,
        "plan": plan,
        "model": model,
        "active_purchase_mode": (
            "cash"
            if _is_cash_price_request(input)
            else "credit"
            if _is_credit_interest(input)
            else values.get("active_purchase_mode")
        ),
        "quote_mode": (
            "cash"
            if _is_cash_price_request(input)
            else "credit"
            if _is_credit_interest(input)
            else values.get("quote_mode")
        ),
    }
    employment_seniority = values.get(ANTIGUEDAD_LABORAL_FIELD_KEY)
    if employment_seniority is not None:
        state["employment_seniority"] = employment_seniority
    seniority_eligible = values.get("FILTRO")
    if seniority_eligible is not None:
        state["seniority_eligible"] = seniority_eligible
    return state


def _state_from_updates(updates: Mapping[str, Any]) -> dict[str, Any]:
    state: dict[str, Any] = {}
    if "MOTO" in updates:
        state["model"] = updates["MOTO"]
    if "CREDITO" in updates:
        state["income_type"] = updates["CREDITO"]
    if "ENGANCHE" in updates:
        state["plan"] = updates["ENGANCHE"]
    return state


def _seniority_updates(seniority: Any) -> dict[str, Any]:
    months = int(getattr(seniority, "normalized_months", 0) or 0)
    return {
        ANTIGUEDAD_LABORAL_FIELD_KEY: str(getattr(seniority, "display_value", "") or "").strip(),
        "FILTRO": months >= 6 if months else False,
    }


def _blocked_nlu_updates(input: SalesAdvisorDecisionInput) -> list[dict[str, Any]]:
    blocked: list[dict[str, Any]] = []
    selector = str(getattr(input.pipeline, "document_requirements_field", "CREDITO") or "CREDITO")
    for field_name, value in _nlu_entity_values(input).items():
        if field_name == selector and _generic_credit_value(value):
            blocked.append(_blocked_update(field_name, value, "generic_credit_value"))
        if str(field_name).upper() == "MOTO" and _generic_model_value(value):
            blocked.append(_blocked_update(field_name, value, "generic_model_value"))
    return blocked


def _generic_model_change_blocked_updates(
    input: SalesAdvisorDecisionInput,
    blocked_updates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    blocked = list(blocked_updates)
    already = {str(item.get("field") or "") for item in blocked}
    for field_name, value in _nlu_entity_values(input).items():
        if str(field_name).upper() == "MOTO" and field_name not in already:
            blocked.append(_blocked_update(field_name, value, "generic_model_change_request"))
    return blocked


def _direct_question_blocked_updates(
    input: SalesAdvisorDecisionInput,
    blocked_updates: list[dict[str, Any]],
    reason: str,
) -> list[dict[str, Any]]:
    blocked = list(blocked_updates)
    already = {str(item.get("field") or "") for item in blocked}
    selector = str(getattr(input.pipeline, "document_requirements_field", "CREDITO") or "CREDITO")
    critical_fields = {selector, "CREDITO", "ENGANCHE", "PLAN", "MOTO", "FILTRO"}
    for field_name, value in _nlu_entity_values(input).items():
        if field_name in already or str(field_name).upper() not in critical_fields:
            continue
        blocked.append(_blocked_update(field_name, value, reason))
    return blocked


def _ambiguous_yes_no_blocked_updates(
    input: SalesAdvisorDecisionInput,
    blocked_updates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    blocked = list(blocked_updates)
    already_blocked = {str(item.get("field") or "") for item in blocked}
    selector = str(getattr(input.pipeline, "document_requirements_field", "CREDITO") or "CREDITO")
    critical_fields = {selector, "CREDITO", "ENGANCHE", "PLAN", "MOTO"}
    for field_name, value in _nlu_entity_values(input).items():
        if field_name in already_blocked or str(field_name).upper() not in critical_fields:
            continue
        blocked.append(
            _blocked_update(
                field_name,
                value,
                "ambiguous_yes_no_without_clear_pending_question",
            )
        )
    return blocked


def _blocked_update(field: Any, value: Any, reason: str) -> dict[str, Any]:
    return {"field": str(field), "attempted_value": value, "reason": reason}


def _acknowledgement_blocked_updates(
    existing: list[dict[str, Any]],
    reason: str,
) -> list[dict[str, Any]]:
    protected = ["MOTO", "CREDITO", "ENGANCHE", "FILTRO", "ANTIGUEDAD_LABORAL"]
    return [*existing, *[_blocked_update(field, None, reason) for field in protected]]


def _nlu_entity_values(input: SalesAdvisorDecisionInput) -> dict[str, Any]:
    entities = getattr(input.nlu, "entities", {}) or {}
    values: dict[str, Any] = {}
    if not isinstance(entities, Mapping):
        return values
    for key, raw in entities.items():
        values[str(key)] = getattr(raw, "value", raw)
    return values


def _resolved_model_entity_value(input: SalesAdvisorDecisionInput) -> str | None:
    candidate = _nlu_entity_values(input).get("MOTO")
    if candidate in (None, "", [], {}):
        return None
    resolved = str(candidate).strip()
    return resolved or None


def _flat_values(data: Mapping[str, Any]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for key, raw in (data or {}).items():
        if isinstance(raw, Mapping) and "value" in raw:
            values[str(key)] = raw.get("value")
        else:
            values[str(key)] = raw
    return values


def _is_credit_interest(input: SalesAdvisorDecisionInput) -> bool:
    if str(getattr(input.operational_intent, "intent_category", "")) == "credit":
        return True
    tokens = set(_normalize(input.inbound_text).split())
    return bool(tokens & _CREDIT_INTENT_TERMS)


def _is_cash_price_request(input: SalesAdvisorDecisionInput) -> bool:
    return _is_cash_price_request_text(input.inbound_text)


def _is_cash_price_request_text(text: str) -> bool:
    normalized = _normalize(text)
    tokens = set(normalized.split())
    if not tokens & _CASH_INTENT_TERMS:
        return False
    price_terms = _QUOTE_REQUEST_TERMS | {"cuanto", "cuanto?", "vale", "valor", "precio"}
    return bool(tokens & price_terms) or "de contado" in normalized


def _is_credit_quote_request(input: SalesAdvisorDecisionInput) -> bool:
    tokens = set(_normalize(input.inbound_text).split())
    if not tokens & _CREDIT_INTENT_TERMS:
        return False
    return _explicit_quote_request(input) or bool(tokens & {"queda", "quedaria", "seria"})


def _is_catalog_selection_reference(text: str) -> bool:
    tokens = set(_normalize(text).split())
    return bool(tokens & {"primera", "primer", "segunda", "tercera", "esa", "ese"})


def _credit_quote_switch_decision(
    input: SalesAdvisorDecisionInput,
    state: dict[str, Any],
    blocked_updates: list[dict[str, Any]],
) -> SalesAdvisorDecision | None:
    if not _is_credit_quote_request(input):
        return None
    if not state.get("model"):
        return None
    credit_state = {**state, "active_purchase_mode": "credit", "quote_mode": "credit"}
    if state.get("plan"):
        return _decision(
            input=input,
            state=credit_state,
            commercial_intent="credit_quote_request",
            next_action="quote",
            confidence=0.93,
            reasons=["credit_quote_request_uses_credit_quote_context"],
            blocked_updates=blocked_updates,
            payload={
                "status": "ok",
                "request_type": "credit_quote_request",
                "quote_mode": "credit",
                "active_purchase_mode": "credit",
                "credit_quote_valid": True,
            },
            blocked_actions=[
                "credit_mode_preserves_model",
                "documents_after_credit_quote_only",
            ],
        )
    return _decision(
        input=input,
        state=credit_state,
        commercial_intent="credit_interest",
        next_action="ask_income_type",
        confidence=0.88,
        reasons=["credit_quote_request_without_income_type"],
        blocked_updates=blocked_updates,
        payload={
            "status": "ok",
            "request_type": "ask_income_type",
            "field_name": getattr(input.pipeline, "document_requirements_field", "CREDITO"),
            "options": _credit_options(input.pipeline),
            "quote_mode": "credit",
            "active_purchase_mode": "credit",
        },
        blocked_actions=[
            "credit_mode_preserves_model",
            "no_ask_documents_before_quote_without_model_plan",
        ],
    )


def _should_attempt_model_resolution_with_credit_context(
    input: SalesAdvisorDecisionInput,
) -> bool:
    if str(getattr(input.operational_intent, "intent_category", "")) == "sales":
        return True
    tokens = _normalize(input.inbound_text).split()
    for index, token in enumerate(tokens):
        if any(ch.isalpha() for ch in token) and any(ch.isdigit() for ch in token):
            return True
        if token == "cc" and index > 0 and any(ch.isdigit() for ch in tokens[index - 1]):
            return True
        if any(ch.isdigit() for ch in token):
            next_token = tokens[index + 1] if index + 1 < len(tokens) else ""
            if next_token == "cc":
                return True
    return False


def _employment_seniority_known(state: dict[str, Any]) -> bool:
    return bool(
        state.get("employment_seniority")
        or state.get("seniority_eligible") is True
        or state.get("FILTRO") is True
    )


def _employment_seniority_context_ready(state: dict[str, Any]) -> bool:
    if str(state.get("income_type") or "").strip() == "Sin Comprobantes":
        return False
    return bool(
        state.get("model")
        and state.get("income_type")
        and state.get("plan")
        and not _employment_seniority_known(state)
    )


def _is_employment_seniority_followup(input: SalesAdvisorDecisionInput) -> bool:
    normalized = _normalize(input.inbound_text)
    tokens = set(normalized.split())
    if any(
        phrase in normalized
        for phrase in (
            "que mas necesitas",
            "que falta",
            "que sigue",
            "quiero avanzar",
            "para seguir",
            "para continuar",
        )
    ):
        return True
    return bool(tokens & {"seguimos", "seguir", "avanzar", "continuar", "listo", "sigue"})


def _is_faq_intent(input: SalesAdvisorDecisionInput) -> bool:
    return str(getattr(input.operational_intent, "intent_category", "")) == "faq"


def _is_direct_faq_question(input: SalesAdvisorDecisionInput) -> bool:
    tokens = set(_normalize(input.inbound_text).split())
    return _is_direct_faq_question_text(tokens)


def _is_direct_faq_question_text(text_or_tokens: str | set[str]) -> bool:
    tokens = (
        set(_normalize(text_or_tokens).split())
        if isinstance(text_or_tokens, str)
        else set(text_or_tokens)
    )
    return bool(
        tokens & _DOWN_PAYMENT_TERMS
        or tokens & _CREDIT_HISTORY_TERMS
        or tokens & _TIMING_TERMS
        or tokens & _LOCATION_TERMS
        or tokens & _PAYOFF_TERMS
    )


def _direct_faq_safe_fallback_decision(
    input: SalesAdvisorDecisionInput,
    state: dict[str, Any],
    blocked_updates: list[dict[str, Any]],
) -> SalesAdvisorDecision | None:
    tokens = set(_normalize(input.inbound_text).split())
    if not tokens or not (tokens & _TIMING_TERMS):
        return None
    pending = _pending_from_requirements(input, state)
    answer = (
        "El tiempo depende de la revision del expediente y de que los documentos queden completos. "
        "En cuanto avancemos con eso te voy diciendo el siguiente paso."
    )
    return _decision(
        input=input,
        state=state,
        commercial_intent="faq_timing_safe_fallback",
        next_action="answer_faq_and_resume",
        confidence=0.72,
        reasons=["timing_question_without_faq_match_uses_safe_non_promissory_answer"],
        blocked_updates=_direct_question_blocked_updates(
            input,
            blocked_updates,
            "timing_faq_fallback_does_not_update_critical_field",
        ),
        payload={
            "status": "ok",
            "answer": answer,
            "answered_intents": ["timing"],
            "detected_intents": ["timing"],
            "intent_stack": ["timing"],
            "resume_pending_action": pending,
            "next_required_step": pending,
            "source": {
                "type": "safe_timing_fallback",
            },
        },
        pending=pending,
        blocked_actions=[
            "no_promise_approval_or_time",
            "no_documents_before_quote_without_model_plan",
        ],
    )


def _is_requirements_question(input: SalesAdvisorDecisionInput) -> bool:
    if _is_document_purpose_or_refusal_question(input.inbound_text):
        return True
    if _is_document_order_followup(input):
        return True
    return _is_requirements_question_text(input.inbound_text, document_upload_signal=_document_upload_signal(input), is_faq_intent=_is_faq_intent(input), has_direct_question=_has_direct_question(input))


def _is_requirements_question_text(
    text: str,
    *,
    document_upload_signal: bool = False,
    is_faq_intent: bool = False,
    has_direct_question: bool = True,
) -> bool:
    normalized = _normalize(text)
    tokens = set(normalized.split())
    if any(phrase in normalized for phrase in _REQUIREMENTS_CONTEXT_PHRASES):
        return True
    if not tokens & _REQUIREMENTS_QUESTION_TERMS:
        return False
    if document_upload_signal:
        return False
    if has_direct_question or is_faq_intent:
        return True
    return bool(tokens & {"papeles", "papeleria", "requisito", "requisitos"})


def _is_document_purpose_or_refusal_question(text: str) -> bool:
    normalized = _normalize(text)
    if not normalized:
        return False
    if any(
        phrase in normalized
        for phrase in (
            "para que los usan",
            "para que usan",
            "para que sirven",
            "porque los piden",
            "por que los piden",
            "nomás porque si",
            "nomas porque si",
            "no voy a mandar documentos",
        )
    ):
        return True
    return bool(
        "document" in normalized
        and any(term in normalized for term in ("explica", "explicame", "porque", "por que"))
    )


def _is_document_order_followup(input: SalesAdvisorDecisionInput) -> bool:
    last_bot_message = _last_bot_message(input)
    if not _looks_like_document_prompt_text(last_bot_message):
        return False
    normalized = _normalize(input.inbound_text)
    tokens = set(normalized.split())
    if not tokens:
        return False
    mentions_send = bool(tokens & {"mando", "manda", "mandar", "mandarte"})
    mentions_order = "primero" in tokens or "que" in tokens or "cual" in tokens
    return mentions_send and mentions_order


def _looks_like_document_prompt_text(text: str | None) -> bool:
    normalized = _normalize(text or "")
    return any(token in normalized for token in ("document", "ine", "domicilio", "papel"))


def _should_defer_acknowledgement_to_model_resolution(
    input: SalesAdvisorDecisionInput,
    state: dict[str, Any],
) -> bool:
    return _has_model_resolution_signal(
        text=input.inbound_text,
        allow_credit_interest=True,
        existing_model=bool(state.get("model")),
    )


def _is_ambiguous_yes_no(input: SalesAdvisorDecisionInput) -> bool:
    if input.pending_confirmation:
        return False
    normalized = _normalize(input.inbound_text)
    if normalized in {_normalize(item) for item in _YES_NO_REPLIES}:
        return True
    tokens = set(normalized.split())
    if len(tokens) > 3:
        return False
    yes_no = {_normalize(item) for item in _YES_NO_REPLIES}
    return bool(tokens & yes_no) and (
        bool(tokens & _DEICTIC_REPLY_TERMS)
        or tokens <= (yes_no | _DEICTIC_REPLY_TERMS)
    )


def _soft_off_topic_decision(
    input: SalesAdvisorDecisionInput,
    state: dict[str, Any],
    blocked_updates: list[dict[str, Any]],
) -> SalesAdvisorDecision | None:
    if not _is_soft_off_topic(input):
        return None
    pending = _pending_from_requirements(input, state) if _flow_active(input, state) else None
    return _decision(
        input=input,
        state=state,
        commercial_intent="soft_off_topic",
        next_action="clarify_ambiguous_yes_no",
        confidence=0.74,
        reasons=["soft_off_topic_does_not_advance_pipeline"],
        blocked_updates=_direct_question_blocked_updates(
            input,
            blocked_updates,
            "soft_off_topic_does_not_update_critical_field",
        ),
        payload={
            "status": "ok",
            "request_type": "clarify_ambiguous_yes_no",
            "clarification_type": "soft_off_topic",
            "pending_to_resume": pending,
            "suggested_clarification": _soft_off_topic_prompt(input, state),
        },
        pending=pending,
        blocked_actions=[
            "no_random_state_contamination",
            "no_auto_ask_field_from_soft_off_topic",
        ],
    )


def _complaint_policy_followup_decision(
    input: SalesAdvisorDecisionInput,
    state: dict[str, Any],
    blocked_updates: list[dict[str, Any]],
) -> SalesAdvisorDecision | None:
    if state.get("model") and state.get("plan") and _is_quote_or_price_complaint(input.inbound_text):
        return _decision(
            input=input,
            state=state,
            commercial_intent="quote_complaint_continue",
            next_action="quote",
            confidence=0.9,
            reasons=["price_or_quote_complaint_requires_quote_repair"],
            blocked_updates=blocked_updates,
            blocked_actions=[
                "no_soft_close_over_quote_complaint",
                "no_documents_before_quote_without_model_plan",
            ],
        )
    policy_class = _complaint_policy_class(input)
    if policy_class == "process_complaint":
        next_missing = _next_missing_after_credit({}, state)
        field_name = str(next_missing.get("field") or "MOTO") if next_missing else "MOTO"
        prompt_override = (
            "Entiendo. Para no repetirnos, solo me faltaria saber que modelo o moto quieres cotizar."
            if field_name == "MOTO"
            else "Entiendo. Para seguir, solo me faltaria confirmar el dato pendiente."
        )
        return _decision(
            input=input,
            state=state,
            commercial_intent="process_complaint_continue",
            next_action="ask_one_missing_field",
            confidence=0.88,
            reasons=["process_complaint_should_continue_with_state"],
            blocked_updates=blocked_updates,
            payload={
                "status": "ok",
                "request_type": "ask_field",
                "field_name": field_name,
                "prompt_override": prompt_override,
            },
            blocked_actions=_standard_blocks(
                input=input,
                state=state,
                next_action="ask_one_missing_field",
            ),
        )
    if _is_price_objection(input.inbound_text) and state.get("model") and state.get("plan"):
        return _decision(
            input=input,
            state=state,
            commercial_intent="price_objection_continue",
            next_action="ask_one_missing_field",
            confidence=0.84,
            reasons=["commercial_price_objection_should_continue_without_handoff"],
            blocked_updates=blocked_updates,
            payload={
                "status": "ok",
                "request_type": "ask_field",
                "field_name": "MOTO",
                "prompt_override": (
                    "Entiendo. Si quieres, revisamos otra opcion o modelo para bajar el enganche y el pago."
                ),
            },
            blocked_actions=[
                *_standard_blocks(
                    input=input,
                    state=state,
                    next_action="ask_one_missing_field",
                ),
                "no_quote_repeat_after_price_objection",
            ],
        )
    return None


def _ambiguous_yes_no_prompt(input: SalesAdvisorDecisionInput, state: dict[str, Any]) -> str:
    if _flow_active(input, state):
        return "Sigo con tu credito. Me confirmas a que te refieres?"
    return "Me confirmas a que te refieres para seguir?"


def _is_soft_off_topic(input: SalesAdvisorDecisionInput) -> bool:
    normalized = _normalize(input.inbound_text)
    tokens = set(normalized.split())
    if not tokens or not (tokens & _SOFT_OFF_TOPIC_TERMS):
        return False
    clear_signal_terms = (
        _CREDIT_INTENT_TERMS
        | _CATALOG_REQUEST_TERMS
        | _CATALOG_COLOR_TERMS
        | _CATALOG_STYLE_TERMS
        | _QUOTE_REQUEST_TERMS
        | _REQUIREMENTS_QUESTION_TERMS
        | _DOWN_PAYMENT_TERMS
        | _CREDIT_HISTORY_TERMS
        | _TIMING_TERMS
    )
    if tokens & clear_signal_terms:
        return False
    if _document_signal(input) or _is_ambiguous_yes_no(input):
        return False
    if str(getattr(input.operational_intent, "intent_category", "")) in {
        "credit",
        "faq",
        "documents",
    }:
        return False
    return True


def _flow_active(input: SalesAdvisorDecisionInput, state: dict[str, Any]) -> bool:
    if state.get("income_type") or state.get("plan") or state.get("model"):
        return True
    history = _recent_history(input)
    for _direction, text in history[-6:]:
        tokens = set(_normalize(text).split())
        if tokens & (
            _CREDIT_INTENT_TERMS
            | _CATALOG_REQUEST_TERMS
            | _CATALOG_STYLE_TERMS
            | _QUOTE_REQUEST_TERMS
            | _REQUIREMENTS_QUESTION_TERMS
            | {"ingresos", "comprobantes", "modelo", "credito"}
        ):
            return True
    return False


def _recent_history(input: SalesAdvisorDecisionInput) -> list[tuple[str, str]]:
    raw = input.metadata.get("recent_history") if isinstance(input.metadata, Mapping) else None
    if not isinstance(raw, list):
        return []
    history: list[tuple[str, str]] = []
    for item in raw:
        if isinstance(item, tuple) and len(item) >= 2:
            history.append((str(item[0]), str(item[1])))
        elif isinstance(item, list) and len(item) >= 2:
            history.append((str(item[0]), str(item[1])))
    return history


def _recent_inbound_block(input: SalesAdvisorDecisionInput) -> list[str]:
    block: list[str] = []
    for direction, text in reversed(_recent_history(input)[-6:]):
        role = _normalize(str(direction or ""))
        candidate = str(text or "").strip()
        if role in {"assistant", "bot", "outbound", "system"}:
            break
        if candidate:
            block.append(candidate)
    block.reverse()
    current = str(input.inbound_text or "").strip()
    if current:
        if not block or block[-1] != current:
            block.append(current)
    return block


def _combined_recent_inbound_block(input: SalesAdvisorDecisionInput) -> str:
    values = _recent_inbound_block(input)
    return "\n".join(value for value in values if value)


def _catalog_browse_intent_from_context(input: SalesAdvisorDecisionInput) -> str | None:
    return catalog_browse_request_type(
        inbound_text=input.inbound_text,
        history=_recent_history(input),
    )


def _last_bot_message(input: SalesAdvisorDecisionInput) -> str | None:
    for direction, text in reversed(_recent_history(input)):
        if _normalize(str(direction or "")) in {"assistant", "bot", "outbound", "system"}:
            candidate = str(text or "").strip()
            if candidate:
                return candidate
    return None


def _last_quote_signature(input: SalesAdvisorDecisionInput) -> str | None:
    for direction, text in reversed(_recent_history(input)[-8:]):
        if _normalize(str(direction or "")) not in {"assistant", "bot", "outbound", "system"}:
            continue
        candidate = str(text or "").strip()
        normalized = _normalize(candidate)
        if "$" in candidate and (
            "enganche" in normalized or "quincenal" in normalized or "contado" in normalized
        ):
            return normalized
    return None


def _confirmed_model_from_bot_message(last_bot_message: str | None) -> str | None:
    text = str(last_bot_message or "").strip()
    if not text:
        return None
    patterns = [
        r"te refieres a ([^?]+)",
        r"quieres ([^?]+)\?",
        r"la ([^?]+) te interesa",
    ]
    normalized = text.replace("\n", " ")
    for pattern in patterns:
        match = re.search(pattern, normalized, flags=re.IGNORECASE)
        if match is None:
            continue
        candidate = str(match.group(1) or "").strip(" .,:;!?")
        if candidate:
            return candidate
    return None


def _looks_like_location_offer_question(last_bot_norm: str) -> bool:
    if "ubicacion" not in last_bot_norm and "direccion" not in last_bot_norm:
        return False
    return "quieres" in last_bot_norm or "te paso" in last_bot_norm


def _looks_like_quote_offer_question(last_bot_norm: str) -> bool:
    if "cotiz" not in last_bot_norm:
        return False
    return "quieres" in last_bot_norm or "te la" in last_bot_norm or "te lo" in last_bot_norm


def _faq_matches_for_text(
    *,
    question: str,
    knowledge_pack: Mapping[str, Any] | None,
    allow_tag_only_match: bool,
    max_matches: int = 3,
) -> list[dict[str, Any]]:
    return answer_faqs_from_pack(
        question=question,
        knowledge_pack=knowledge_pack,
        allow_tag_only_match=allow_tag_only_match,
        max_matches=max_matches,
    )


def _faq_payload_from_matches(
    matches: list[dict[str, Any]],
    *,
    knowledge_pack: Mapping[str, Any] | None,
    detected_intents: list[str],
    answered_intents: list[str],
    unresolved_intents: list[str],
    intent_stack: list[str],
    pending: dict[str, Any] | None,
    next_required_step: dict[str, Any] | None,
    primary_commercial_goal: str,
    pending_bot_question: dict[str, Any] | None,
    yes_no_context_resolution: str | None,
    resolved_followup_intent: str | None,
    resolved_followup_entity: str | None,
    context_resolution_confidence: float | None,
) -> dict[str, Any]:
    answers = [
        {
            "topic": str(item.get("topic") or "").strip(),
            "question": str(item.get("question") or "").strip(),
            "answer": str(item.get("answer") or "").strip(),
            "score": float(item.get("score") or 0),
        }
        for item in matches
        if str(item.get("answer") or "").strip()
    ]
    if len(answers) == 1:
        combined_answer = answers[0]["answer"]
    else:
        combined_answer = "\n".join(
            f"{entry['topic'].capitalize()}: {entry['answer']}" for entry in answers
        )
    source_topic = answers[0]["topic"] if answers else None
    pack_version = knowledge_pack.get("pack_version") if isinstance(knowledge_pack, Mapping) else None
    payload: dict[str, Any] = {
        "status": "ok",
        "answer": combined_answer,
        "answers": answers,
        "topic": source_topic,
        "source": {
            "type": "knowledge_pack",
            "topic": source_topic,
            "knowledge_pack_version": str(pack_version) if pack_version else None,
        },
        "detected_intents": detected_intents,
        "answered_intents": answered_intents,
        "unresolved_intents": unresolved_intents,
        "intent_stack": intent_stack,
        "primary_commercial_goal": primary_commercial_goal,
        "next_required_step": next_required_step,
        "pending_bot_question": pending_bot_question,
        "yes_no_context_resolution": yes_no_context_resolution,
        "resolved_followup_intent": resolved_followup_intent,
        "resolved_followup_entity": resolved_followup_entity,
        "context_resolution_confidence": context_resolution_confidence,
        "matches": [
            {
                "pregunta": entry["question"],
                "respuesta": entry["answer"],
                "score": entry["score"],
                "faq_id": None,
                "collection_id": None,
                "source": "knowledge_pack",
            }
            for entry in answers
        ],
    }
    if pending is not None:
        payload["resume_pending_action"] = pending
    return payload


def _primary_commercial_goal(state: dict[str, Any]) -> str:
    if not state.get("income_type"):
        return "falta_ingreso"
    if not state.get("model"):
        return "falta_modelo"
    if not _employment_seniority_known(state) and state.get("income_type") != "Pensionados":
        return "falta_antiguedad"
    if state.get("plan") and state.get("model"):
        return "listo_para_quote"
    return "flujo_activo"


def _specific_requirements_followup_answer(
    *,
    inbound_text: str,
    requirements_payload: dict[str, Any] | None,
) -> str | None:
    normalized = _normalize(inbound_text)
    if (
        "comprobante" in normalized
        and any(term in normalized for term in ("nombre de", "mi mama", "mi mamá", "otra persona"))
    ):
        return (
            "Para comprobante de domicilio puede revisarse aunque este a nombre de otra persona; "
            "si fuera comprobante de ingresos, ese si tendria que corresponder al ingreso que vas a usar."
        )
    subject = infer_requirement_subject(inbound_text)
    if not subject or not isinstance(requirements_payload, dict):
        return None
    required_docs = requirements_payload.get("required") or requirements_payload.get("missing") or []
    return requirement_subject_answer(subject=subject, required_docs=required_docs)


def _next_required_step_payload(
    input: SalesAdvisorDecisionInput,
    state: dict[str, Any],
) -> dict[str, Any] | None:
    if not state.get("income_type"):
        return {"type": "ask_field", "field": "CREDITO"}
    if not state.get("model"):
        return {"type": "ask_field", "field": "MOTO"}
    if (
        _employment_seniority_context_ready(state)
        and not _employment_seniority_known(state)
        and state.get("income_type") != "Pensionados"
    ):
        return {"type": "ask_field", "field": ANTIGUEDAD_LABORAL_FIELD_KEY}
    pending = _pending_from_requirements(input, state)
    return pending if isinstance(pending, dict) else None


def _pending_acknowledgement_field(last_bot_message: str | None, state: dict[str, Any]) -> str | None:
    normalized = _normalize(last_bot_message or "")
    if not normalized:
        if not state.get("income_type"):
            return "CREDITO"
        if state.get("plan") and not state.get("model"):
            return "MOTO"
        return None
    if any(term in normalized for term in ("cuanto tiempo", "antiguedad", "empleo actual")):
        if _employment_seniority_known(state):
            return None
        return ANTIGUEDAD_LABORAL_FIELD_KEY
    if (
        any(term in normalized for term in ("ingresos", "nomina", "por fuera"))
        and any(term in normalized for term in ("como", "recibes", "pagan"))
    ):
        return "CREDITO"
    if any(term in normalized for term in ("modelo", "moto", "categoria")) and any(
        term in normalized for term in ("dime", "cual", "quieres", "interesa")
    ):
        return "MOTO"
    if any(term in normalized for term in ("enganche", "anticipo")):
        return "ENGANCHE"
    return None


def _documents_state_for_acknowledgement(
    input: SalesAdvisorDecisionInput,
    state: dict[str, Any],
    last_bot_message: str | None,
) -> dict[str, Any] | None:
    last_bot_norm = _normalize(last_bot_message or "")
    if not (
        _has_document_progress(input)
        or any(term in last_bot_norm for term in ("document", "papel", "falt", "ine", "comprobante"))
    ):
        return None
    result = get_missing_documents(pipeline=input.pipeline, state={"extracted_data": input.extracted_data})
    if isinstance(result, ToolNoDataResult):
        return None
    pending = _pending_from_missing_documents(result)
    if not isinstance(pending, dict):
        return None
    if pending.get("type") == "ask_missing_documents":
        return {
            "kind": "missing_documents",
            "missing": [str(item) for item in pending.get("missing") or [] if str(item).strip()],
        }
    if pending.get("type") == "requirements_complete":
        return {
            "kind": "requirements_complete",
            "required": [str(item) for item in pending.get("required") or [] if str(item).strip()],
        }
    return None


def _soft_off_topic_prompt(input: SalesAdvisorDecisionInput, state: dict[str, Any]) -> str:
    if _flow_active(input, state):
        return "Sigo con tu credito. Me confirmas que quieres revisar?"
    return "Me confirmas a que te refieres para seguir?"


def _non_document_attachment_decision(
    input: SalesAdvisorDecisionInput,
    state: dict[str, Any],
    blocked_updates: list[dict[str, Any]],
) -> SalesAdvisorDecision | None:
    if not input.attachments:
        return None
    intent = _attachment_intent(input)
    if intent.has_trusted_document or intent.has_unresolved_document_like_attachment:
        return None
    if not intent.has_non_document_attachment:
        return None
    suggested = intent.suggested_clarification
    if intent.ignored_labels and not suggested:
        suggested = _attachment_resume_prompt(state)
    if not suggested:
        suggested = (
            "Recibi el adjunto, pero no puedo usarlo como dato del tramite. Me confirmas que es?"
        )
    pending = _pending_from_requirements(input, state)
    return _decision(
        input=input,
        state=state,
        commercial_intent="attachment_context",
        next_action="clarify_ambiguous_yes_no",
        confidence=0.78,
        reasons=[
            "attachment_intent_policy_no_state_write",
            *list(intent.reason_codes),
        ],
        blocked_updates=blocked_updates,
        payload={
            "status": "ok",
            "request_type": "clarify_ambiguous_yes_no",
            "clarification_type": "attachment_context",
            "attachment_intent": {
                "labels": list(intent.labels),
                "kinds": list(intent.kinds),
                "reason_codes": list(intent.reason_codes),
            },
            "pending_to_resume": pending,
            "suggested_clarification": suggested,
        },
        pending=pending,
        blocked_actions=[
            "no_documents_as_purchase_intent",
            "no_mark_document_received_without_trusted_label",
            "no_write_moto_without_model_evidence",
        ],
    )


def _attachment_resume_prompt(state: Mapping[str, Any]) -> str:
    if not state.get("income_type"):
        return "Recibi la imagen; sigo con tu credito. Dime como recibes tus ingresos."
    if not state.get("model"):
        return "Recibi la imagen; sigo con tu credito. Dime que modelo te interesa."
    return "Recibi la imagen; sigo con tu credito. Me confirmas que quieres revisar?"


def _attachment_intent(input: SalesAdvisorDecisionInput) -> AttachmentIntentResult:
    return classify_attachment_intent(
        attachments=input.attachments,
        metadata=input.metadata,
        pipeline=input.pipeline,
    )


def _document_signal(input: SalesAdvisorDecisionInput) -> bool:
    if _document_upload_signal(input):
        return True
    return str(getattr(input.operational_intent, "intent_category", "")) == "documents"


def _is_text_document_claim_without_evidence(
    input: SalesAdvisorDecisionInput,
    state: dict[str, Any],
) -> bool:
    if _document_upload_signal(input):
        return False
    if not _pending_from_requirements(input, state):
        return False
    normalized = _normalize(input.inbound_text)
    if not normalized:
        return False
    if not any(
        phrase in normalized
        for phrase in (
            "ya te mande",
            "ya mande",
            "ya te envie",
            "ya envie",
            "te mando",
            "te envie",
        )
    ):
        return False
    return any(
        token in normalized
        for token in ("ine", "frente", "atras", "comprobante", "domicilio", "documento")
    )


def _is_documents_submission_confirmation(
    input: SalesAdvisorDecisionInput,
    state: dict[str, Any],
) -> bool:
    if _document_upload_signal(input):
        return False
    normalized = _normalize(input.inbound_text)
    if not normalized:
        return False
    if not any(phrase in normalized for phrase in _DOCUMENT_SUBMISSION_CONFIRMATION_PHRASES):
        return False
    if _pending_from_requirements(input, state) is not None:
        return True
    return _has_document_progress(input)


def _document_upload_signal(input: SalesAdvisorDecisionInput) -> bool:
    if any(getattr(write, "accepted", False) for write in input.vision_writes or []):
        return True
    intent = _attachment_intent(input)
    return intent.has_trusted_document or intent.has_unresolved_document_like_attachment


def _document_updates(input: SalesAdvisorDecisionInput) -> dict[str, str]:
    updates: dict[str, str] = {}
    for write in input.vision_writes:
        key = str(getattr(write, "doc_key", "") or "").strip()
        if key and getattr(write, "accepted", False):
            updates[key] = "ok"
    for doc in _attachment_intent(input).accepted_documents:
        updates.setdefault(doc.key, "ok")
    return updates


def _attachment_semantic_labels(input: SalesAdvisorDecisionInput) -> list[str]:
    return list(_attachment_intent(input).labels)


def _has_document_progress(input: SalesAdvisorDecisionInput) -> bool:
    extracted = _flat_values(input.extracted_data)
    document_keys = {
        str(getattr(doc, "key", "")).strip()
        for doc in getattr(input.pipeline, "documents_catalog", []) or []
        if str(getattr(doc, "key", "")).strip()
    }
    return any(extracted.get(key) not in (None, "", [], {}) for key in document_keys)


def _document_key_for_label(pipeline: Any, label: str) -> str | None:
    return document_key_for_attachment_label(pipeline, label)


def _document_label(pipeline: Any, key: str) -> str:
    for doc in getattr(pipeline, "documents_catalog", []) or []:
        if str(getattr(doc, "key", "")) == key:
            return str(getattr(doc, "label", None) or key)
    return key


def _pending_from_requirements(
    input: SalesAdvisorDecisionInput,
    state: dict[str, Any],
    *,
    updates: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    extracted = dict(input.extracted_data or {})
    for key, value in (updates or {}).items():
        extracted[str(key)] = {"value": value, "confidence": 1.0, "source_turn": 0}
    if state.get("income_type") and "CREDITO" not in extracted:
        extracted["CREDITO"] = {"value": state["income_type"], "confidence": 1.0, "source_turn": 0}
    result = get_missing_documents(pipeline=input.pipeline, state={"extracted_data": extracted})
    if isinstance(result, ToolNoDataResult):
        return _pending_from_last_bot_documents(input)
    missing = [
        str(getattr(doc, "label", None) or getattr(doc, "key", ""))
        for doc in result.missing
        if str(getattr(doc, "label", None) or getattr(doc, "key", "")).strip()
    ]
    if missing:
        return {"type": "ask_missing_documents", "missing": missing}
    return _pending_from_last_bot_documents(input)


def _pending_from_last_bot_documents(
    input: SalesAdvisorDecisionInput,
) -> dict[str, Any] | None:
    last_bot_message = _last_bot_message(input)
    doc_labels = extract_document_labels_from_text(last_bot_message or "")
    if not doc_labels:
        return None
    return {"type": "ask_missing_documents", "missing": doc_labels}


def _pending_from_missing_documents(result: Any) -> dict[str, Any] | None:
    missing = [
        str(getattr(doc, "label", None) or getattr(doc, "key", ""))
        for doc in getattr(result, "missing", []) or []
        if str(getattr(doc, "label", None) or getattr(doc, "key", "")).strip()
    ]
    if missing:
        return {"type": "ask_missing_documents", "missing": missing}
    required = [
        str(getattr(doc, "label", None) or getattr(doc, "key", ""))
        for doc in getattr(result, "required", []) or []
        if str(getattr(doc, "label", None) or getattr(doc, "key", "")).strip()
    ]
    if required:
        return {"type": "requirements_complete", "required": required}
    return None


def _next_missing_after_credit(
    updates: Mapping[str, Any],
    state: dict[str, Any],
) -> dict[str, Any] | None:
    merged = {**state, **_state_from_updates(updates)}
    if not merged.get("model"):
        return {"type": "ask_field", "field": "MOTO", "alternatives": ["modelo", "categoria"]}
    if not merged.get("plan"):
        return {"type": "ask_field", "field": "ENGANCHE"}
    return None


def _credit_options(pipeline: Any) -> list[dict[str, Any]]:
    options: list[dict[str, Any]] = []
    for item in build_credit_plan_menu(pipeline):
        options.append(
            {
                "key": str(item.get("selection_key") or ""),
                "label": str(item.get("selection_label") or item.get("selection_key") or ""),
                "aliases": list(item.get("aliases") or []),
                "display_number": item.get("display_number"),
                "visible_label": item.get("visible_label"),
                "down_payment": item.get("down_payment"),
            }
        )
    return options


def _negative_receipts_signal(text: str) -> bool:
    normalized = _normalize(text)
    return any(phrase in normalized for phrase in _NEGATIVE_RECEIPTS_PHRASES)


def _positive_receipts_signal(text: str) -> bool:
    normalized = _normalize(text)
    return any(phrase in normalized for phrase in _POSITIVE_RECEIPTS_PHRASES)


def _payroll_card_signal(text: str) -> bool:
    normalized = _normalize(text)
    tokens = set(normalized.split())
    if "nomina en tarjeta" in normalized:
        return True
    if normalized in {"tarjeta", "en tarjeta", "con tarjeta"}:
        return True
    if "tarjeta" not in tokens:
        return False
    return any(term in normalized for term in ("nomina", "deposit", "transfer"))


def _deposit_formal_income_confirmation_signal(text: str) -> bool:
    normalized = _normalize(text)
    tokens = set(normalized.split())
    if _negative_receipts_signal(text):
        return False
    has_deposit_context = any(term in normalized for term in ("deposit", "transfer"))
    has_formal_context = bool(tokens & {"nomina", "formal"}) or "comprobable" in tokens
    has_confirmation = bool(tokens & {_normalize(item) for item in _YES_NO_REPLIES}) or any(
        term in normalized for term in ("uso", "usar", "con ese", "ese ingreso")
    )
    return has_deposit_context and has_formal_context and has_confirmation


def _income_disambiguation_signals(text: str) -> IncomeDisambiguationSignals:
    normalized = _normalize(text)
    tokens = set(normalized.split())
    has_nomina = "nomina" in tokens
    has_receipts = _positive_receipts_signal(text)
    has_card = _payroll_card_signal(text)
    has_deposit = any(term in normalized for term in ("deposit", "transfer"))
    has_negative = _negative_receipts_signal(text)
    explicit_multiple_income = (
        "dos trabajos" in normalized
        or "dos ingresos" in normalized
        or ("uno" in tokens and "otro" in tokens)
    )
    dual_income_detected = (
        explicit_multiple_income
        or (
            not has_negative
            and ("negocio" in tokens or "fuera" in tokens)
            and (has_deposit or has_nomina)
        )
    )
    payroll_ambiguous = has_nomina and not has_card and not has_receipts
    deposit_ambiguous = has_deposit and not has_card and not has_receipts and not has_negative
    needs_income_disambiguation = dual_income_detected or payroll_ambiguous or deposit_ambiguous
    blocked_reason = None
    if dual_income_detected:
        blocked_reason = "dual_income_detected"
    elif payroll_ambiguous:
        blocked_reason = "payroll_ambiguous"
    elif deposit_ambiguous:
        blocked_reason = "deposit_ambiguous"
    return IncomeDisambiguationSignals(
        income_ambiguity=payroll_ambiguous or deposit_ambiguous or dual_income_detected,
        payroll_ambiguous=payroll_ambiguous,
        deposit_ambiguous=deposit_ambiguous,
        dual_income_detected=dual_income_detected,
        needs_income_disambiguation=needs_income_disambiguation,
        credit_plan_write_blocked_reason=blocked_reason,
    )


def _credit_mode_switch_preserves_existing_model(input: SalesAdvisorDecisionInput) -> bool:
    if not _is_credit_interest(input):
        return False
    if _has_model_resolution_signal(
        text=input.inbound_text,
        allow_credit_interest=False,
        existing_model=True,
    ):
        return False
    normalized = _normalize(input.inbound_text)
    return bool(normalized and any(term in normalized for term in _CREDIT_INTENT_TERMS))


def _dual_income_selection_signal(text: str) -> bool:
    normalized = _normalize(text)
    tokens = set(normalized.split())
    if (
        "efectivo" in tokens
        and "sin comprobantes" not in normalized
        and "por fuera" not in normalized
    ):
        return False
    if any(
        phrase in normalized
        for phrase in (
            "quiero usar",
            "quiero tomar",
            "prefiero usar",
            "uso el deposito",
            "usar el deposito",
            "mejor por fuera",
            "entonces tarjeta",
            "con tarjeta",
            "entonces sin comprobantes",
            "sin comprobantes",
            "no tengo comprobante",
            "no se puede comprobar",
        )
    ):
        return True
    if "comprobable" in tokens and bool(tokens & {"uso", "usar", "prefiero", "quiero"}):
        return True
    return False


def _income_disambiguation_answer(
    signals: IncomeDisambiguationSignals,
    *,
    inbound_text: str = "",
) -> str:
    if signals.dual_income_detected:
        normalized = _normalize(inbound_text)
        tokens = set(normalized.split())
        if "efectivo" in tokens and bool(tokens & {"usar", "uso", "tomar", "quiero", "prefiero"}):
            return (
                "Si quieres usar el ingreso en efectivo o por fuera, lo revisamos como "
                "Sin Comprobantes. Confirmame si avanzamos con Sin Comprobantes."
            )
        if any(term in normalized for term in ("conviene", "mejor", "comprobable", "aplica")):
            return (
                "Si ese deposito es nomina formal en tarjeta, normalmente conviene revisarlo "
                "como ingreso comprobable porque puede manejar menor enganche. Si no se puede "
                "comprobar, lo revisamos como Sin Comprobantes. Dime cual ingreso quieres usar "
                "o cual puedes comprobar mejor."
            )
        return (
            "Podemos revisar el ingreso comprobable si ese deposito es nomina formal en tarjeta. "
            "Si no se puede comprobar, se revisa como Sin Comprobantes. "
            "Dime cual ingreso quieres usar o si ese deposito si es nomina formal."
        )
    if signals.deposit_ambiguous:
        return (
            "Para decirte el plan correcto necesito saber si ese deposito es nomina formal en tarjeta "
            "o si es otro ingreso depositado."
        )
    return (
        "Para decirte el plan correcto necesito confirmar si esa nomina te la depositan en tarjeta "
        "o si te pagan con recibos."
    )


def _selected_income_source_for_plan(selection_key: str) -> str | None:
    normalized = _normalize(selection_key)
    if "nomina tarjeta" in normalized:
        return "deposito_nomina_tarjeta"
    if "nomina recib" in normalized:
        return "nomina_recibos"
    if "sin comprobantes" in normalized:
        return "ingreso_por_fuera_sin_comprobantes"
    if "guardia" in normalized:
        return "guardia_seguridad"
    if "pension" in normalized:
        return "pension"
    return None


def _mark_dual_income_selection_resolved(
    payload: dict[str, Any],
    *,
    selection_key: str,
    confidence: float,
) -> None:
    selected_source = _selected_income_source_for_plan(selection_key)
    if selected_source is None:
        return
    payload["dual_income_resolution_required"] = False
    payload["selected_income_source"] = selected_source
    payload["selected_income_source_confidence"] = confidence
    payload["documents_blocked_by_dual_income"] = False
    payload["quote_blocked_by_dual_income"] = False
    payload["pending_flow_forced_to_income_disambiguation"] = False
    policy_trace = payload.get("policy_trace")
    if not isinstance(policy_trace, dict):
        policy_trace = {}
    policy_trace.update(
        {
            "income_ambiguity": False,
            "payroll_ambiguous": False,
            "deposit_ambiguous": False,
            "dual_income_detected": False,
            "needs_income_disambiguation": False,
            "credit_plan_write_blocked_reason": None,
            "dual_income_resolution_required": False,
            "selected_income_source": selected_source,
            "selected_income_source_confidence": confidence,
            "documents_blocked_by_dual_income": False,
            "quote_blocked_by_dual_income": False,
            "pending_flow_forced_to_income_disambiguation": False,
        }
    )
    payload["policy_trace"] = policy_trace


def _recent_income_disambiguation_context(input: SalesAdvisorDecisionInput) -> bool:
    recent_context = " ".join(
        str(text or "")
        for direction, text in _recent_history(input)[-4:]
        if _normalize(str(direction or "")) in {"assistant", "bot", "outbound", "system", "user", "inbound"}
    )
    summary = str(input.conversation_summary or "")
    normalized = _normalize(" ".join([recent_context, summary]))
    return any(
        term in normalized
        for term in (
            "dos trabajos",
            "dos ingresos",
            "uno por fuera",
            "otro me cae deposito",
            "nomina formal",
            "sin comprobantes",
            "comprobar",
            "tarjeta",
            "recibos",
            "deposito",
        )
    )


def _recent_dual_income_context(input: SalesAdvisorDecisionInput) -> bool:
    recent_context = " ".join(str(text or "") for _, text in _recent_history(input)[-8:])
    normalized = _normalize(" ".join([recent_context, str(input.conversation_summary or "")]))
    tokens = set(normalized.split())
    return (
        "dos trabajos" in normalized
        or "dos ingresos" in normalized
        or ("uno" in tokens and "otro" in tokens and ("fuera" in tokens or "deposito" in tokens))
        or ("uno por fuera" in normalized and "deposit" in normalized)
    )


def _guardia_signal(text: str) -> bool:
    normalized = _normalize(text)
    return any(
        phrase in normalized
        for phrase in (
            "soy guardia",
            "guardia",
            "guardia de seguridad",
            "seguridad privada",
        )
    )


def _has_down_payment_signal(text: str) -> bool:
    normalized = _normalize(text)
    tokens = set(normalized.split())
    if tokens & _DOWN_PAYMENT_TERMS:
        return True
    return "%" in normalized or "por ciento" in normalized


def _recent_inbound_has_model_context(input: SalesAdvisorDecisionInput) -> bool:
    for direction, text in _recent_history(input)[-4:]:
        if _normalize(str(direction or "")) != "inbound":
            continue
        if _has_model_resolution_signal(
            text=text,
            allow_credit_interest=True,
            existing_model=False,
        ):
            return True
    return False


def _early_model_change_signal(input: SalesAdvisorDecisionInput) -> bool:
    normalized = _normalize(input.inbound_text)
    if not any(phrase in normalized for phrase in _EARLY_MODEL_CHANGE_PHRASES):
        return False
    if not _recent_inbound_has_model_context(input):
        return False
    return _has_model_resolution_signal(
        text=input.inbound_text,
        allow_credit_interest=True,
        existing_model=False,
    )


def _prioritize_commercial_model_turn_over_faq(
    input: SalesAdvisorDecisionInput,
    state: dict[str, Any],
) -> bool:
    if not (state.get("income_type") or state.get("plan")):
        return False
    if not _has_down_payment_signal(input.inbound_text):
        return False
    if state.get("model") and state.get("plan"):
        return True
    return _has_model_resolution_signal(
        text=input.inbound_text,
        allow_credit_interest=True,
        existing_model=bool(state.get("model")),
    )


def _needs_payroll_receipts_confirmation(
    *,
    inbound_text: str,
    credit_plan_key: str,
) -> bool:
    # Once the deterministic plan resolver lands on Nomina Tarjeta, the
    # commercial flow should move to model/quote, not reopen a receipts
    # disambiguation loop from the raw wording of the same turn.
    return False


def _is_catalog_request(input: SalesAdvisorDecisionInput) -> bool:
    normalized = _normalize(input.inbound_text)
    tokens = set(normalized.split())
    if "catalogo" in tokens or "catalog" in tokens:
        return True
    if _is_catalog_color_question(input):
        return True
    return bool(tokens & _CATALOG_REQUEST_TERMS) and (
        bool(tokens & _CATALOG_REQUEST_VERBS) or "?" in input.inbound_text
    )


def _is_catalog_color_question(input: SalesAdvisorDecisionInput) -> bool:
    tokens = set(_normalize(input.inbound_text).split())
    if not (tokens & _CATALOG_COLOR_TERMS):
        return False
    return _has_direct_question(input) or bool(tokens & _CATALOG_REQUEST_VERBS)


def _catalog_category(text: str) -> str | None:
    tokens = set(_normalize(text).split())
    category_aliases = {
        "cuatrimotos": "cuatrimoto",
        "deportivas": "deportiva",
        "motocarros": "motocarro",
        "motonetas": "motoneta",
        "scooter": "motoneta",
        "urbanas": "urbana",
    }
    for token in _CATALOG_STYLE_PRIORITY:
        if token in tokens:
            return category_aliases.get(token, token)
    if "doble" in tokens and "proposito" in tokens:
        return "doble proposito"
    return None


def _is_unresolved_catalog_reference(text: str) -> bool:
    tokens = set(_normalize(text).split())
    if not tokens:
        return False
    reference = any(token.startswith("anunci") or token.startswith("public") for token in tokens)
    if not reference:
        return False
    catalog_nouns = {"moto", "motos", "motocicleta", "modelo", "modelos", "opcion", "opciones"}
    return bool(tokens & catalog_nouns) or bool(tokens & {"quiero", "busco", "interesa"})


def _is_vague_model_reference(text: str) -> bool:
    tokens = set(_normalize(text).split())
    if not tokens:
        return False
    if _is_unresolved_catalog_reference(text):
        return True
    deictic = {"esta", "este", "esa", "ese", "aquella", "aquel"}
    catalog_nouns = {"moto", "motos", "motocicleta", "modelo", "modelos"}
    return bool(tokens & deictic) and bool(tokens & catalog_nouns)


def _deictic_current_quote_request(text: str) -> bool:
    tokens = set(_normalize(text).split())
    if not tokens:
        return False
    deictic = {"esta", "este", "esa", "ese", "aquella", "aquel"}
    quote_terms = _QUOTE_REQUEST_TERMS | {"cuanto", "cuanta", "queda", "quedaria", "seria"}
    return bool(tokens & deictic) and bool(tokens & quote_terms)


def _model_queries(text: str) -> list[str]:
    normalized = _normalize(text)
    raw_tokens = normalized.split()
    tokens = [
        token
        for token in raw_tokens
        if token not in _MODEL_QUERY_STOPWORDS
        and (len(token) > 1 or any(ch.isdigit() for ch in token))
    ]
    queries: list[str] = []

    def add(value: str) -> None:
        cleaned = value.strip()
        if cleaned and cleaned not in queries:
            queries.append(cleaned)

    for marker_index, token in enumerate(raw_tokens):
        if token not in {"actualiza", "cambio", "cambiar", "mejor", "prefiero"}:
            continue
        tail = [
            item
            for item in raw_tokens[marker_index + 1 :]
            if item not in _MODEL_QUERY_STOPWORDS
            and (len(item) > 1 or any(ch.isdigit() for ch in item))
        ]
        if tail:
            add(" ".join(tail))
            for size in (3, 2):
                for index in range(0, max(0, len(tail) - size + 1)):
                    add(" ".join(tail[index : index + size]))
    add(normalized)
    if tokens:
        add(" ".join(tokens))
    for token in tokens:
        if any(ch.isdigit() for ch in token) and any(ch.isalpha() for ch in token):
            add(token)
    for size in (3, 2):
        for index in range(0, max(0, len(raw_tokens) - size + 1)):
            window = raw_tokens[index : index + size]
            if not _model_query_window(window):
                continue
            compact = [
                token
                for token in window
                if token not in {"el", "la", "los", "las", "un", "una"}
            ]
            if set(window) & {"moto", "motocicleta", "modelo"} and compact:
                add(" ".join(compact))
            add(" ".join(window))
    for size in (3, 2):
        for index in range(0, max(0, len(tokens) - size + 1)):
            add(" ".join(tokens[index : index + size]))
    for token in tokens:
        add(token)
    return queries[:8]


def _credit_preserving_model_change_queries(text: str) -> list[str]:
    raw_tokens = _normalize(text).split()
    queries: list[str] = []

    def add(value: str) -> None:
        cleaned = value.strip()
        if cleaned and cleaned not in queries:
            queries.append(cleaned)

    for marker_index, token in enumerate(raw_tokens):
        if token not in _MODEL_CHANGE_QUERY_MARKERS:
            continue
        tail = [
            item
            for item in raw_tokens[marker_index + 1 :]
            if item not in _MODEL_CHANGE_CONTEXT_STOPWORDS
            and (len(item) > 1 or any(ch.isdigit() for ch in item))
        ]
        if not tail:
            continue
        add(" ".join(tail))
        for size in (3, 2):
            for index in range(0, max(0, len(tail) - size + 1)):
                add(" ".join(tail[index : index + size]))
    return queries[:4]


def _model_query_window(tokens: list[str]) -> bool:
    if not tokens:
        return False
    content = [
        token
        for token in tokens
        if token not in _MODEL_QUERY_STOPWORDS
        and (len(token) > 1 or any(ch.isdigit() for ch in token))
    ]
    if not content:
        return False
    model_nouns = {"moto", "motocicleta", "modelo"}
    return bool(set(tokens) & model_nouns) or len(content) >= 2 or any(
        any(ch.isdigit() for ch in token) for token in tokens
    )


def _looks_like_model_change(text: str) -> bool:
    tokens = set(_normalize(text).split())
    return bool(tokens & {"mejor", "cambio", "cambiar", "prefiero", "actualiza"})


def _is_generic_model_change_request(input: SalesAdvisorDecisionInput) -> bool:
    tokens = set(_normalize(input.inbound_text).split())
    model_terms = {"moto", "motos", "modelo", "modelos", "opcion", "opciones"}
    if not (tokens & model_terms and tokens & _GENERIC_MODEL_MODIFIERS):
        return False
    return _looks_like_model_change(input.inbound_text) or bool(
        tokens & {"quiero", "ver", "ensenar"}
    )


def _has_direct_question(input: SalesAdvisorDecisionInput) -> bool:
    if "?" in input.inbound_text or "¿" in input.inbound_text:
        return True
    tokens = set(_normalize(input.inbound_text).split())
    question_terms = {"que", "cuanto", "cuanta", "cual", "cuando", "donde", "como"}
    return bool(tokens & question_terms)


def _complaint_policy_class(input: SalesAdvisorDecisionInput) -> str | None:
    for signal in list(getattr(input.operational_intent, "signals", []) or []):
        if not isinstance(signal, str):
            continue
        if signal.startswith("complaint_policy:"):
            return signal.split(":", 1)[1]
    return None


def _is_price_objection(text: str) -> bool:
    normalized = _normalize(text)
    return any(
        phrase in normalized
        for phrase in (
            "esta caro",
            "esta muy caro",
            "se me hace mucho",
        )
    )


def _is_quote_or_price_complaint(text: str) -> bool:
    normalized = _normalize(text)
    return any(
        phrase in normalized
        for phrase in (
            "no voy a mandar nada antes de que me digas cuanto sale",
            "no voy a mandarte nada antes de que me digas cuanto sale",
            "primero dime cuanto",
            "primero dime cuanto sale",
            "no me has cotizado",
            "si ya me dijiste",
            "eso ya lo dijiste",
            "ya me dijiste",
            "primero dime el precio",
            "antes dime cuanto sale",
        )
    )


def _has_recent_quote_context(input: SalesAdvisorDecisionInput) -> bool:
    recent_outbound = [
        _normalize(text)
        for direction, text in _recent_history(input)[-6:]
        if _normalize(str(direction or "")) in {"assistant", "bot", "outbound", "system"}
        and str(text or "").strip()
    ]
    return any(
        "$" in text and ("enganche" in text or "quincenal" in text or "contado" in text)
        for text in recent_outbound
    )


def _is_post_quote_progress_followup(text: str) -> bool:
    normalized = _normalize(text)
    if not normalized:
        return False
    if any(phrase in normalized for phrase in _POST_QUOTE_PROGRESS_PHRASES):
        return True
    tokens = set(normalized.split())
    return bool(tokens & {"seguimos", "seguir", "avanzamos", "avanzar", "vamos", "dale"})


def _is_affirmative_post_quote_requirements_followup(
    *,
    text: str,
    last_bot_message: str | None,
    pending: Mapping[str, Any] | None,
) -> bool:
    if not isinstance(pending, Mapping) or str(pending.get("type") or "").strip() != "ask_missing_documents":
        return False
    message = str(last_bot_message or "").strip()
    normalized_last_bot = _normalize(message)
    if "$" not in message or not any(
        term in normalized_last_bot for term in ("enganche", "quincenal", "contado", "pago")
    ):
        return False
    normalized = _normalize(text)
    if not normalized:
        return False
    return normalized in _POST_QUOTE_PROGRESS_ACK_TERMS


def _has_model_resolution_signal(
    *,
    text: str,
    allow_credit_interest: bool,
    existing_model: bool,
) -> bool:
    normalized = _normalize(text)
    tokens = normalized.split()
    if not tokens:
        return False
    if existing_model and _looks_like_model_change(text):
        return True
    if _is_unresolved_catalog_reference(text) or _is_vague_model_reference(text):
        return False
    for index, token in enumerate(tokens):
        if any(ch.isalpha() for ch in token) and any(ch.isdigit() for ch in token):
            return True
        if token == "cc" and index > 0 and any(ch.isdigit() for ch in tokens[index - 1]):
            return True
        if any(ch.isdigit() for ch in token):
            next_token = tokens[index + 1] if index + 1 < len(tokens) else ""
            if next_token == "cc":
                return True
    if tokens[0] in _MODEL_SIGNAL_ARTICLES:
        remaining = [
            token
            for token in tokens[1:]
            if token not in _MODEL_QUERY_STOPWORDS and token not in _MODEL_SIGNAL_DISALLOWED_TOKENS
        ]
        if remaining:
            return True
    if tokens[0] in {"quiero", "busco"} or "interesa" in tokens:
        remaining = [
            token
            for token in tokens[1:]
            if token not in _MODEL_QUERY_STOPWORDS
            and token not in _MODEL_SIGNAL_DISALLOWED_TOKENS
            and token not in _CREDIT_INTENT_TERMS
        ]
        if remaining:
            return True
    if len(tokens) == 1:
        token = tokens[0]
        if (
            len(token) >= 3
            and token not in _MODEL_SIGNAL_DISALLOWED_TOKENS
            and token not in _MODEL_QUERY_STOPWORDS
        ):
            return True
    return allow_credit_interest and _looks_like_model_change(text)


def _resolved_model_entity_supported_by_text(
    input: SalesAdvisorDecisionInput,
    candidate: str,
    *,
    existing_model: bool,
) -> bool:
    if _is_catalog_selection_reference(input.inbound_text):
        return True
    if _has_model_resolution_signal(
        text=input.inbound_text,
        allow_credit_interest=True,
        existing_model=existing_model,
    ):
        return True
    inbound_tokens = set(_normalize(input.inbound_text).split())
    candidate_tokens = {
        token
        for token in _normalize(candidate).split()
        if token not in _MODEL_QUERY_STOPWORDS
        and token not in _MODEL_SIGNAL_DISALLOWED_TOKENS
        and (len(token) >= 3 or any(ch.isdigit() for ch in token))
    }
    return bool(inbound_tokens & candidate_tokens)


def _is_payroll_receipts_confirmation_reply(text: str) -> bool:
    normalized = _normalize(text)
    if any(
        phrase in normalized
        for phrase in (
            "si tengo recibos",
            "tengo recibos",
            "recibos de nomina",
            "si recibos",
            "me dan recibos",
            "si me dan recibos",
        )
    ):
        return True
    return normalized in {"si", "claro", "sale", "va", "simon", "ok"}


def _quote_allowed(input: SalesAdvisorDecisionInput) -> bool:
    if _explicit_quote_request(input):
        return True
    return not _has_direct_question(input)


def _explicit_quote_request(input: SalesAdvisorDecisionInput) -> bool:
    return _explicit_quote_request_text(input.inbound_text, pending_confirmation=input.pending_confirmation)


def _explicit_quote_request_text(
    text: str,
    *,
    pending_confirmation: str | None = None,
) -> bool:
    tokens = set(_normalize(text).split())
    if tokens & _QUOTE_REQUEST_TERMS:
        return True
    if tokens & _DOWN_PAYMENT_TERMS:
        return True
    if "cuanto" in tokens and (
        len(tokens) <= 2
        or bool(tokens & {"queda", "quedaria", "seria", "sale", "mensualidad", "pago"})
    ):
        return True
    pending = str(pending_confirmation or "")
    if "quote" in pending or "cotiz" in _normalize(pending):
        return True
    return False


def _generic_credit_value(value: Any) -> bool:
    return _normalize(str(value or "")) in _GENERIC_CREDIT_VALUES


def _generic_model_value(value: Any) -> bool:
    normalized = _normalize(str(value or ""))
    if normalized in _GENERIC_MODEL_VALUES:
        return True
    tokens = set(normalized.split())
    model_terms = {"moto", "motos", "modelo", "modelos", "opcion", "opciones"}
    allowed_generic = model_terms | _GENERIC_MODEL_MODIFIERS | {"la", "el", "una", "un"}
    return (
        bool(tokens & model_terms)
        and bool(tokens & _GENERIC_MODEL_MODIFIERS)
        and tokens <= allowed_generic
    )


def _standard_blocks(
    *,
    input: SalesAdvisorDecisionInput,
    state: dict[str, Any],
    next_action: str,
) -> list[str]:
    blocks: list[str] = []
    if state.get("income_type") == "Sin Comprobantes" and str(state.get("plan") or "") == "20%":
        blocks.append("no_ask_antiguedad_for_sin_comprobantes_20")
    if state.get("active_purchase_mode") == "cash":
        blocks.extend(
            [
                "cash_mode_blocks_credit_flow",
                "no_ask_credit_context_for_cash_price",
                "no_ask_documents_for_cash_price",
                "no_credit_requirements_for_cash_price",
            ]
        )
    if not (state.get("model") and state.get("plan")):
        blocks.extend(
            [
                "no_quote_without_model_and_plan",
                "no_ask_documents_before_quote_without_model_plan",
            ]
        )
    if state.get("model"):
        blocks.append("no_ask_model_already_resolved")
    if next_action == "answer_faq_and_resume":
        blocks.append("no_faq_as_quote")
    if _document_signal(input):
        blocks.append("no_documents_as_purchase_intent")
    return blocks


def _tool_log(
    tool_name: str,
    input_payload: dict[str, Any],
    output_payload: Any,
    started_at: float,
) -> dict[str, Any]:
    latency_ms = int((time.perf_counter() - started_at) * 1000) if started_at else 0
    return {
        "tool_name": tool_name,
        "input_payload": input_payload,
        "output_payload": output_payload,
        "latency_ms": latency_ms,
        "error": None,
    }


def _normalize(value: str) -> str:
    return normalize_whatsapp_text(value)


def _dedupe(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


__all__ = [
    "SalesAdvisorDecision",
    "SalesAdvisorDecisionInput",
    "SalesAdvisorDecisionPolicy",
]
