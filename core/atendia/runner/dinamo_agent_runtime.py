from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from atendia.runner.agent_final_response import (
    AgentFinalResponseRequest,
    build_agent_final_response,
)
from atendia.runner.composer_protocol import ComposerOutput
from atendia.runner.state_write_policy import StateWritePolicyRequest, apply_state_write_policy


DINAMO_TENANT_NAMES = {"dinamo motos nl"}


@dataclass(frozen=True)
class DinamoAgentStateWrite:
    field: str
    value: Any
    source: str
    reason: str | None = None


@dataclass(frozen=True)
class DinamoAgentToolCall:
    tool: str
    input: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DinamoAgentTurnResult:
    final_text: str
    tool_calls: list[DinamoAgentToolCall]
    tool_results: list[dict[str, Any]]
    proposed_state_writes: list[DinamoAgentStateWrite]
    accepted_state_writes: list[DinamoAgentStateWrite]
    rejected_state_writes: list[DinamoAgentStateWrite]
    stage_update: str | None
    trace_payload: dict[str, Any]
    should_enqueue: bool
    handoff_requested: bool
    safety_flags: list[str]
    state_after: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DinamoRuntimeSelection:
    runtime_path: str
    flag_source: str | None
    tenant_id: str | None
    tenant_name: str
    channel: str | None
    test_run: str | None
    reason_selected: str
    sandbox_allowed: bool
    live_limited_allowed: bool
    real_outbox_blocked: bool


@dataclass
class _AgentPlan:
    current_questions: list[str] = field(default_factory=list)
    primary_intent: str = "continue"
    tool_plan: list[dict[str, Any]] = field(default_factory=list)
    proposed_state_writes: list[DinamoAgentStateWrite] = field(default_factory=list)
    final_action: str = "agent_response"
    draft_text: str = "Claro, te ayudo. Me dices un poquito mas para orientarte bien?"
    action_payload: dict[str, Any] = field(default_factory=dict)
    stage_update: str | None = None
    handoff_requested: bool = False
    safety_flags: list[str] = field(default_factory=list)


def dinamo_agent_first_enabled(
    tenant: Any,
    config: dict[str, Any] | None = None,
    settings: Any | None = None,
) -> bool:
    """Return whether a caller should route this turn to the agent-first runtime."""

    if _tenant_name(tenant) not in DINAMO_TENANT_NAMES:
        return False
    return _config_flag_enabled(config) or _settings_flag_enabled(settings) or _env_flag_enabled()


def select_dinamo_runtime(
    tenant: Any,
    config: dict[str, Any] | None = None,
    *,
    customer_attrs: dict[str, Any] | None = None,
    customer_id: str | None = None,
    customer_phone_e164: str | None = None,
    channel: str | None = None,
    test_run: str | None = None,
    inbound_metadata: dict[str, Any] | None = None,
    settings: Any | None = None,
) -> DinamoRuntimeSelection:
    tenant_name = _tenant_name(tenant)
    tenant_id = _maybe_attr(tenant, "id")
    resolved_channel = _first_text(
        channel,
        _mapping_value(customer_attrs, "channel"),
        _mapping_value(inbound_metadata, "channel"),
        _mapping_value(config, "channel"),
    )
    resolved_test_run = _first_text(
        test_run,
        _mapping_value(customer_attrs, "test_run"),
        _mapping_value(inbound_metadata, "test_run"),
        _mapping_value(config, "test_run"),
    )
    flag_enabled, flag_source = _flag_status(config=config, settings=settings)

    if tenant_name not in DINAMO_TENANT_NAMES:
        return DinamoRuntimeSelection(
            runtime_path="conversation_runner",
            flag_source=flag_source,
            tenant_id=str(tenant_id) if tenant_id else None,
            tenant_name=tenant_name,
            channel=resolved_channel,
            test_run=resolved_test_run,
            reason_selected="tenant_not_dinamo",
            sandbox_allowed=False,
            live_limited_allowed=False,
            real_outbox_blocked=False,
        )
    if not flag_enabled:
        return DinamoRuntimeSelection(
            runtime_path="conversation_runner",
            flag_source=flag_source,
            tenant_id=str(tenant_id) if tenant_id else None,
            tenant_name=tenant_name,
            channel=resolved_channel,
            test_run=resolved_test_run,
            reason_selected="flag_off",
            sandbox_allowed=False,
            live_limited_allowed=False,
            real_outbox_blocked=False,
        )

    sandbox_allowed = _sandbox_or_canary_allowed(
        channel=resolved_channel,
        test_run=resolved_test_run,
        inbound_metadata=inbound_metadata,
    )
    live_limited_allowed = _live_limited_allowed(
        config=config,
        tenant_id=str(tenant_id) if tenant_id else None,
        customer_id=customer_id,
        customer_phone_e164=customer_phone_e164,
    )
    if (
        _live_limited_restricts_to_allowlist(config)
        and not sandbox_allowed
        and not live_limited_allowed
    ):
        return DinamoRuntimeSelection(
            runtime_path="conversation_runner",
            flag_source=flag_source,
            tenant_id=str(tenant_id) if tenant_id else None,
            tenant_name=tenant_name,
            channel=resolved_channel,
            test_run=resolved_test_run,
            reason_selected="dinamo_live_limited_not_allowlisted",
            sandbox_allowed=False,
            live_limited_allowed=False,
            real_outbox_blocked=False,
        )
    real_outbox_blocked = not (sandbox_allowed or live_limited_allowed)
    return DinamoRuntimeSelection(
        runtime_path="dinamo_agent_first",
        flag_source=flag_source,
        tenant_id=str(tenant_id) if tenant_id else None,
        tenant_name=tenant_name,
        channel=resolved_channel,
        test_run=resolved_test_run,
        reason_selected=(
            "dinamo_flag_on_sandbox_canary"
            if sandbox_allowed
            else "dinamo_flag_on_live_limited_allowlist"
            if live_limited_allowed
            else "dinamo_flag_on_real_outbox_blocked_for_canary"
        ),
        sandbox_allowed=sandbox_allowed,
        live_limited_allowed=live_limited_allowed,
        real_outbox_blocked=real_outbox_blocked,
    )


def dinamo_runtime_path(
    tenant: Any,
    config: dict[str, Any] | None = None,
    customer_attrs: dict[str, Any] | None = None,
    settings: Any | None = None,
) -> str:
    return select_dinamo_runtime(
        tenant,
        config,
        customer_attrs=customer_attrs,
        customer_id=None,
        customer_phone_e164=None,
        settings=settings,
    ).runtime_path


async def run_dinamo_agent_turn(
    *,
    tenant: Any,
    conversation: Any | None = None,
    customer: Any | None = None,
    inbound_message: Any,
    history: list[tuple[str, str]] | None = None,
    current_state: dict[str, Any] | None = None,
    attachments: list[Any] | None = None,
    config: dict[str, Any] | None = None,
    tool_dispatch: Any | None = None,
    settings: Any | None = None,
    brand_facts: dict[str, Any] | None = None,
) -> DinamoAgentTurnResult:
    """Run one Dinamo agent-first turn without writing DB rows or enqueueing outbox.

    The function is intentionally callable as a helper in phase one. It reuses
    existing tool dispatch, state write policy, and final-response authority,
    but leaves WhatsApp transport and persistence to the existing runner path.
    """

    inbound_text = _message_text(inbound_message)
    safe_history = list(history or [])
    safe_state = dict(current_state or {})
    safe_attachments = list(attachments or [])
    tenant_id = _tenant_id(tenant)

    plan = _build_initial_plan(
        inbound_text=inbound_text,
        history=safe_history,
        current_state=safe_state,
        attachments=safe_attachments,
    )

    if tool_dispatch is not None:
        await _apply_credit_plan_resolution(
            plan=plan,
            inbound_text=inbound_text,
            tool_dispatch=tool_dispatch,
        )
        await _execute_tools(
            plan=plan,
            tenant_id=tenant_id,
            inbound_text=inbound_text,
            current_state=safe_state,
            tool_dispatch=tool_dispatch,
        )

    write_policy = _apply_state_write_policy(
        inbound_text=inbound_text,
        current_state=safe_state,
        proposed_state_writes=plan.proposed_state_writes,
    )
    accepted_writes = write_policy["accepted"]
    rejected_writes = write_policy["rejected"]
    state_after = _merge_state(safe_state, accepted_writes)

    action_payload = dict(plan.action_payload)
    if plan.final_action == "quote" and not action_payload.get("status"):
        action_payload.setdefault("status", "no_data")
    if plan.final_action == "quote" and action_payload.get("status") == "ok":
        state_after["last_quote"] = {"value": _public_quote_payload(action_payload), "source": "quote_tool"}
    if plan.final_action == "classify_document" and safe_attachments:
        plan.stage_update = "doc_incompleta"
    elif plan.final_action == "classify_document" and not safe_attachments:
        plan.safety_flags.append("doc_incompleta_blocked_without_attachment")

    final_response = build_agent_final_response(
        AgentFinalResponseRequest(
            user_message=inbound_text,
            history=safe_history,
            state=state_after,
            tool_results=action_payload,
            final_action=plan.final_action,
            advisor_brain_result={
                "intent": plan.primary_intent,
                "current_questions": plan.current_questions,
                "natural_response": plan.draft_text,
            },
            composer_output=ComposerOutput(messages=[plan.draft_text]),
            brand_facts=_brand_facts(tenant=tenant, customer=customer, config=config, explicit=brand_facts),
            allow_document_resume=not _previous_bot_asked_documents(safe_history),
        )
    )

    tool_results = [
        {
            "tool": item.get("tool") or item.get("tool_name"),
            "payload": item.get("payload", item),
        }
        for item in _as_list(action_payload.get("_tool_results"))
    ]
    if action_payload and not tool_results:
        tool_results = [{"tool": plan.final_action, "payload": action_payload}]
    source_metadata = _source_metadata_from_tool_results(tool_results, action_payload)

    blocked_reasons = [
        str(item.reason)
        for item in rejected_writes
        if item.reason
    ]
    trace_payload = {
        "runtime_path": "dinamo_agent_first",
        "agent_question_understanding": {
            "primary_intent": plan.primary_intent,
            "current_questions": plan.current_questions,
            "input_slots_present": sorted(_present_state_slots(safe_state)),
            "attachments_count": len(safe_attachments),
        },
        "tool_plan": plan.tool_plan,
        "tool_results": tool_results,
        "state_writes_accepted": [_write_to_dict(item) for item in accepted_writes],
        "state_writes_rejected": [_write_to_dict(item) for item in rejected_writes],
        **source_metadata,
        "final_text_source": "agent_final_response",
        "final_text": final_response.text,
        "current_question_answered": bool(final_response.answered_intents)
        or not plan.current_questions
        or "current_question_not_answered" not in final_response.reasons,
        "blocked_reasons": _dedupe([*blocked_reasons, *final_response.reasons]),
        "final_action": plan.final_action,
        "state_after": state_after,
        "conversation_id": _maybe_attr(conversation, "id"),
    }

    return DinamoAgentTurnResult(
        final_text=final_response.text,
        tool_calls=[DinamoAgentToolCall(tool=item["tool"], input=item.get("input", {})) for item in plan.tool_plan],
        tool_results=tool_results,
        proposed_state_writes=plan.proposed_state_writes,
        accepted_state_writes=accepted_writes,
        rejected_state_writes=rejected_writes,
        stage_update=plan.stage_update,
        trace_payload=trace_payload,
        should_enqueue=True,
        handoff_requested=plan.handoff_requested,
        safety_flags=_dedupe(plan.safety_flags),
        state_after=state_after,
    )


def _build_initial_plan(
    *,
    inbound_text: str,
    history: list[tuple[str, str]],
    current_state: dict[str, Any],
    attachments: list[Any],
) -> _AgentPlan:
    normalized = _normalize(inbound_text)
    questions = _question_intents(normalized)
    state_model = _state_value(current_state, "MOTO")
    state_credit = _state_value(current_state, "CREDITO")
    state_down = _state_value(current_state, "ENGANCHE")
    plan = _AgentPlan(current_questions=questions)

    if _is_payment_support_request(normalized):
        plan.primary_intent = "payment_support"
        plan.final_action = "handoff"
        plan.handoff_requested = True
        plan.safety_flags.append("payment_support_requires_manual_handling")
        plan.proposed_state_writes.append(
            DinamoAgentStateWrite(field="agent_paused", value=True, source="agent_brain")
        )
        plan.draft_text = (
            "Para pagos o separados te paso con Francisco o un asesor para que te confirme "
            "bien y no mover datos sensibles por aqui."
        )
        return plan

    if "humano" in questions:
        plan.primary_intent = "handoff"
        plan.final_action = "handoff"
        plan.handoff_requested = True
        plan.proposed_state_writes.append(
            DinamoAgentStateWrite(field="agent_paused", value=True, source="agent_brain")
        )
        plan.draft_text = "Claro, lo dejo para que Francisco o un asesor lo revise contigo."
        return plan

    if _is_no_attachment_document_ack(normalized):
        plan.primary_intent = "document_without_attachment_ack"
        plan.final_action = "classify_document"
        plan.safety_flags.append("document_claim_without_attachment")
        plan.draft_text = (
            "Va, entonces no lo cuento como recibido todavia. Mandamelo como foto o archivo "
            "y te confirmo cuando entre."
        )
        return plan

    if _is_document_attachment_followup(normalized, history):
        plan.primary_intent = "document_without_attachment_followup"
        plan.final_action = "classify_document"
        plan.safety_flags.append("document_claim_without_attachment")
        plan.draft_text = (
            "Mandamelo otra vez como foto o archivo desde aqui. Cuando entre, te confirmo "
            "que sigue con el tramite."
        )
        return plan

    if _is_document_status_question(normalized):
        plan.primary_intent = "document_upload_status"
        plan.final_action = "classify_document"
        plan.safety_flags.append("document_status_without_attachment")
        plan.draft_text = _document_status_text(normalized)
        return plan

    if _is_closing_ack(normalized):
        plan.primary_intent = "closing_ack"
        plan.final_action = "agent_response"
        if _is_visit_closing(normalized):
            plan.draft_text = (
                "Va, te esperamos en Benito Juarez 801, Centro Monterrey. "
                "Si puedes, antes de venir te dejo con un asesor para confirmar horario y disponibilidad."
            )
        elif _has_quote_context(current_state) or state_model:
            plan.draft_text = "Perfecto, aqui seguimos. Si quieres avanzar, te dejo con un asesor para cerrarlo bien."
        else:
            plan.draft_text = "Perfecto, aqui seguimos cuando gustes."
        return plan

    direct_answers = [item for item in questions if item in {"ubicacion", "buro", "liquidacion"}]
    if direct_answers:
        plan.primary_intent = direct_answers[0]
        plan.final_action = "answer_faq"
        plan.tool_plan.append(
            {
                "tool": "lookup_faq",
                "input": {"inbound_text": inbound_text, "intents": direct_answers},
            }
        )
        if _contains_model_hint(normalized):
            plan.tool_plan.append(
                {
                    "tool": "search_catalog",
                    "input": {"query_text": inbound_text, "result_limit": 3},
                }
            )
        plan.action_payload = {"status": "ok"}
        plan.draft_text = "Claro, te contesto eso primero."
        return plan

    if "documentos" in questions:
        plan.primary_intent = "documents"
        plan.final_action = "classify_document"
        if _has_quote_context(current_state):
            plan.draft_text = _document_request_text(normalized)
        else:
            plan.draft_text = (
                "Primero te cotizo bien la moto y el plan; ya con eso te digo exactamente "
                "que documentos siguen."
            )
        if attachments:
            plan.stage_update = "doc_incompleta"
        return plan

    seniority = _parse_seniority_months(normalized)
    if seniority is not None:
        plan.primary_intent = "employment_seniority"
        plan.final_action = "ask_credit_context"
        plan.proposed_state_writes.append(
            DinamoAgentStateWrite(
                field="ANTIGUEDAD_LABORAL",
                value={"raw_text": inbound_text, "normalized_months": seniority},
                source="agent_brain",
            )
        )
        plan.proposed_state_writes.append(
            DinamoAgentStateWrite(
                field="FILTRO",
                value=seniority >= 6,
                source="agent_brain",
            )
        )
        plan.draft_text = (
            "Perfecto, con esa antiguedad si podemos revisar plan. "
            "Ahora dime como recibes tus ingresos para ubicar tu plan."
        )
        return plan

    if _dual_income_ambiguous(normalized):
        plan.primary_intent = "dual_income_ambiguity"
        plan.final_action = "ask_credit_context"
        plan.safety_flags.append("dual_income_requires_selection")
        plan.draft_text = (
            "Como tienes dos ingresos, dime cual quieres comprobar para el plan: "
            "el que te depositan o el que recibes por fuera?"
        )
        return plan

    if _price_objection(normalized):
        plan.primary_intent = "price_objection"
        plan.final_action = "agent_response"
        plan.draft_text = (
            "Te entiendo, no es poquito. Podemos revisar el enganche o ver una opcion "
            "mas ajustada para que el pago te quede mas comodo."
        )
        return plan

    if _asks_more_down_payment(normalized):
        plan.primary_intent = "more_down_payment"
        plan.final_action = "agent_response"
        plan.draft_text = (
            "Si, normalmente puedes dar mas enganche para bajar el pago. "
            "En catalogo tengo opciones de 10%, 15%, 20% y 30%, segun tu plan y validacion. "
            "Si quieres, te paso con un asesor para aterrizar cual te conviene."
        )
        return plan

    if _is_ambiguous_income_followup(normalized) and state_model and not state_credit:
        plan.primary_intent = "income_ambiguity_followup"
        plan.final_action = "ask_credit_context"
        plan.safety_flags.append("credito_ambiguous")
        plan.draft_text = (
            "Va, ya tengo la moto. Para el plan solo confirmame si esa nomina viene "
            "con recibos, en tarjeta, o si seria sin comprobantes."
        )
        return plan

    income = _income_plan(normalized)
    if income == "ambiguous":
        plan.primary_intent = "income_ambiguity"
        plan.final_action = "ask_credit_context"
        plan.safety_flags.append("credito_ambiguous")
        plan.draft_text = (
            "Cuando dices que te depositan en tarjeta, es nomina con recibos "
            "o deposito sin comprobantes?"
        )
        return plan
    if income:
        plan.primary_intent = "income_plan"
        plan.final_action = "ask_field"
        plan.action_payload = {"field_name": "MOTO"}
        plan.proposed_state_writes.extend(
            [
                DinamoAgentStateWrite(
                    field="CREDITO",
                    value=income["credit"],
                    source="agent_brain",
                ),
                DinamoAgentStateWrite(
                    field="ENGANCHE",
                    value=income["down_payment"],
                    source="agent_brain",
                ),
            ]
        )
        if state_model:
            plan.final_action = "quote"
            plan.tool_plan.append(
                {
                    "tool": "quote",
                    "input": {
                        "candidate_queries": [state_model],
                        "plan_code": income["down_payment"],
                    },
                }
            )
        model_prompt = _ask_model_with_recent_candidates(current_state)
        if model_prompt.startswith("Ya tengo tu plan"):
            plan.draft_text = model_prompt
        else:
            plan.draft_text = "Va, con ese dato ya tengo tu plan. " + model_prompt
        return plan

    price_requested = "precio" in questions
    last_quote = _last_quote_payload(current_state)
    if price_requested and last_quote:
        plan.primary_intent = "quote_replay"
        plan.final_action = "quote"
        plan.action_payload = last_quote
        plan.draft_text = _quote_draft_text(last_quote)
        return plan

    if price_requested and state_credit and state_down and not state_model:
        recent_match = _recent_candidate_match(normalized, current_state)
        if recent_match:
            plan.primary_intent = "quote_recent_candidate"
            plan.final_action = "quote"
            plan.proposed_state_writes.extend(_model_selected_writes(recent_match))
            plan.tool_plan.append(
                {
                    "tool": "quote",
                    "input": {"candidate_queries": [recent_match], "plan_code": state_down},
                }
            )
            plan.draft_text = "Te paso la cotizacion de esa opcion."
            return plan
        plan.primary_intent = "quote_missing_model"
        plan.final_action = "ask_field"
        plan.action_payload = {"field_name": "MOTO"}
        plan.safety_flags.append("price_with_plan_missing_model")
        plan.draft_text = _ask_model_with_recent_candidates(current_state)
        return plan

    if price_requested and state_model and state_credit and state_down:
        plan.primary_intent = "quote"
        plan.final_action = "quote"
        plan.tool_plan.append(
            {
                "tool": "quote",
                "input": {"candidate_queries": [state_model], "plan_code": state_down},
            }
        )
        plan.draft_text = "Te paso la cotizacion con los datos que ya tenemos."
        return plan

    if price_requested and _price_mentions_model(normalized):
        plan.primary_intent = "model_price_resolution"
        plan.final_action = "search_catalog"
        plan.safety_flags.append("price_requested_before_credit_context")
        plan.tool_plan.append(
            {
                "tool": "search_catalog",
                "input": {"query_text": inbound_text, "result_limit": 3},
            }
        )
        plan.draft_text = (
            "Va, reviso el modelo en catalogo. Si hay varias opciones te digo cuales son "
            "para cotizar la correcta."
        )
        return plan

    if _is_generic_credit_purchase(normalized):
        plan.primary_intent = "credit_purchase_start"
        plan.final_action = "ask_field"
        plan.action_payload = {"field_name": "MOTO"}
        plan.draft_text = (
            "Claro, te ayudo. Que modelo tienes en mente? Si todavia no sabes, dime si la buscas para trabajo, ciudad o algo mas deportivo."
        )
        return plan

    if _looks_like_model_request(normalized):
        recent_match = _recent_candidate_match(normalized, current_state)
        if recent_match:
            plan.primary_intent = "recent_candidate_selection"
            plan.proposed_state_writes.extend(_model_selected_writes(recent_match))
            if state_credit and state_down:
                plan.final_action = "quote"
                plan.tool_plan.append(
                    {
                        "tool": "quote",
                        "input": {"candidate_queries": [recent_match], "plan_code": state_down},
                    }
                )
                plan.draft_text = "Va, te cotizo esa opcion."
            else:
                plan.final_action = "ask_credit_context"
                plan.action_payload = {"field_name": "CREDITO", "resolved_model": recent_match}
                plan.draft_text = (
                    f"Va, tomamos la {recent_match}. Para darte precio a credito, dime como recibes tus ingresos."
                )
            return plan
        if _should_keep_recent_candidates(normalized, current_state):
            plan.primary_intent = "recent_candidate_category_followup"
            plan.final_action = "ask_field"
            plan.action_payload = {"field_name": "MOTO"}
            plan.draft_text = _ask_model_with_recent_candidates(current_state)
            return plan
        plan.primary_intent = "model_resolution"
        plan.final_action = "search_catalog"
        plan.tool_plan.append(
            {
                "tool": "search_catalog",
                "input": {"query_text": inbound_text, "result_limit": 3},
            }
        )
        plan.draft_text = "Va, reviso en catalogo y te digo que opciones encuentro."
        return plan

    if price_requested:
        plan.primary_intent = "quote_missing_context"
        plan.final_action = "ask_field"
        missing_field = "MOTO" if not state_model else "CREDITO"
        plan.action_payload = {"field_name": missing_field}
        plan.safety_flags.append("price_without_quote_context")
        if state_model:
            plan.draft_text = (
                f"Va, ya tengo la {state_model}. Para cotizarte bien dime como recibes tus ingresos."
            )
        elif state_credit and state_down:
            plan.draft_text = _ask_model_with_recent_candidates(current_state)
        else:
            plan.draft_text = (
                "Para darte precio exacto necesito el modelo y como recibes tus ingresos."
            )
        return plan

    plan.primary_intent = "continue"
    if _has_quote_context(current_state):
        plan.final_action = "agent_response"
        plan.draft_text = "Va, seguimos con tu cotizacion. Si quieres avanzar, te dejo con un asesor para revisarla contigo."
    elif state_model and state_credit:
        plan.final_action = "agent_response"
        plan.draft_text = f"Va, ya tengo la {state_model} y tu plan. Te reviso la cotizacion cuando me digas."
    elif state_model:
        plan.final_action = "ask_credit_context"
        plan.draft_text = f"Ya tengo la {state_model}. Solo dime como recibes tus ingresos para cotizarla bien."
    elif state_credit:
        plan.final_action = "ask_field"
        plan.action_payload = {"field_name": "MOTO"}
        plan.draft_text = _ask_model_with_recent_candidates(current_state)
    else:
        plan.final_action = "ask_credit_context"
        plan.draft_text = "Claro, te ayudo. Que modelo buscas?"
    return plan


async def _execute_tools(
    *,
    plan: _AgentPlan,
    tenant_id: UUID | None,
    inbound_text: str,
    current_state: dict[str, Any],
    tool_dispatch: Any,
) -> None:
    for step in list(plan.tool_plan):
        tool = step["tool"]
        if tool == "search_catalog":
            result = await tool_dispatch.search_catalog(
                tenant_id=tenant_id,
                query_text=inbound_text,
                result_limit=step.get("input", {}).get("result_limit", 3),
                catalog_browse_intent=False,
                catalog_browse_preview_limit=3,
                catalog_url=None,
                collection_ids=[],
                exclude_model_names=None,
            )
            payload = _tool_payload(result)
            previous_payload = dict(plan.action_payload or {})
            previous_tool_results = _as_list(previous_payload.get("_tool_results"))
            plan.action_payload = {
                **previous_payload,
                **payload,
                "_tool_results": [
                    *previous_tool_results,
                    {"tool": "search_catalog", "payload": payload},
                ],
            }
            candidates = _catalog_candidates(payload)
            auto_selected_model = _auto_select_catalog_candidate(
                inbound_text=inbound_text,
                current_state=current_state,
                candidates=candidates,
            )
            if candidates and not auto_selected_model:
                plan.proposed_state_writes.append(
                    DinamoAgentStateWrite(
                        field="recent_catalog_candidates",
                        value=candidates[:3],
                        source="catalog_tool",
                        reason="catalog_candidate_options",
                    )
                )
            if len(candidates) > 1 and not auto_selected_model:
                plan.final_action = "ask_field"
                plan.action_payload = {
                    **plan.action_payload,
                    "field_name": "MOTO",
                    "catalog_candidates": candidates[:3],
                }
                plan.draft_text = _candidate_options_text(candidates)
                continue
            model = auto_selected_model or _catalog_model_name(payload)
            if model:
                credit_ready = _state_value(current_state, "CREDITO") and _state_value(current_state, "ENGANCHE")
                plan.proposed_state_writes.append(
                    DinamoAgentStateWrite(
                        field="MOTO",
                        value=model,
                        source="catalog_tool",
                        reason="catalog_canonical_model",
                    )
                )
                if auto_selected_model:
                    plan.proposed_state_writes.append(
                        DinamoAgentStateWrite(
                            field="recent_catalog_candidates",
                            value=[],
                            source="catalog_tool",
                            reason="auto_selected_model_clear_candidates",
                        )
                    )
                if plan.final_action == "answer_faq":
                    answer = str(previous_payload.get("answer") or plan.draft_text or "").strip()
                    plan.action_payload = {
                        **plan.action_payload,
                        "resolved_model": model,
                    }
                    plan.draft_text = (
                        f"{answer} Y seguimos con la {model}; dime como recibes tus ingresos "
                        "para cotizarla bien."
                    ).strip()
                if plan.primary_intent in {"model_price_resolution", "model_resolution"} and not credit_ready:
                    plan.final_action = "ask_credit_context"
                    plan.action_payload = {
                        **plan.action_payload,
                        "field_name": "CREDITO",
                        "resolved_model": model,
                    }
                    plan.draft_text = (
                        f"Va, si te refieres a la {model}, te la puedo cotizar; "
                        "para darte precio exacto a credito dime como recibes tus ingresos."
                    )
                if credit_ready:
                    step_quote = {
                        "tool": "quote",
                        "input": {
                            "candidate_queries": [model],
                            "plan_code": _state_value(current_state, "ENGANCHE"),
                        },
                    }
                    plan.tool_plan.append(step_quote)
                    quote_result = await _run_quote_tool(
                        tenant_id=tenant_id,
                        tool_dispatch=tool_dispatch,
                        model=model,
                        plan_code=_state_value(current_state, "ENGANCHE"),
                    )
                    plan.final_action = "quote"
                    plan.action_payload = quote_result
                    plan.draft_text = _quote_draft_text(quote_result)
            else:
                plan.safety_flags.append("catalog_model_not_resolved")
        elif tool == "quote":
            model = (step.get("input") or {}).get("candidate_queries", [None])[0]
            plan_code = (step.get("input") or {}).get("plan_code")
            plan.action_payload = await _run_quote_tool(
                tenant_id=tenant_id,
                tool_dispatch=tool_dispatch,
                model=model,
                plan_code=plan_code,
            )
            plan.draft_text = _quote_draft_text(plan.action_payload)
        elif tool == "lookup_faq":
            if hasattr(tool_dispatch, "lookup_faq"):
                result = await tool_dispatch.lookup_faq(
                    tenant_id=tenant_id,
                    inbound_text=inbound_text,
                    collection_ids=[],
                    pack_faq_probe=None,
                    pack_faq_probe_ok=False,
                )
                payload = _tool_payload(result)
                if payload.get("answer"):
                    answer = _faq_answer_text(
                        normalized=_normalize(inbound_text),
                        plan=plan,
                        payload=payload,
                    )
                    resume = _resume_after_faq(plan=plan, current_state=current_state)
                    plan.action_payload = {
                        **plan.action_payload,
                        "answer": answer,
                        "topic": payload.get("topic"),
                        "_tool_results": [{"tool": "lookup_faq", "payload": payload}],
                    }
                    plan.draft_text = " ".join(part for part in (answer, resume) if part).strip()


async def _apply_credit_plan_resolution(
    *,
    plan: _AgentPlan,
    inbound_text: str,
    tool_dispatch: Any,
) -> None:
    if plan.primary_intent != "income_plan" or not hasattr(tool_dispatch, "resolve_credit_plan"):
        return
    result = await tool_dispatch.resolve_credit_plan(inbound_text=inbound_text)
    payload = _tool_payload(result)
    if payload.get("status") != "ok":
        return
    credit = _first_text(payload.get("selection_key"), payload.get("tipo_credito"), payload.get("credit"))
    down_payment = _first_text(payload.get("plan_credito"), payload.get("down_payment"), payload.get("plan_code"))
    if not credit or not down_payment:
        return
    plan.tool_plan.insert(0, {"tool": "resolve_credit_plan", "input": {"inbound_text": inbound_text}})
    plan.proposed_state_writes = [
        item for item in plan.proposed_state_writes if item.field not in {"CREDITO", "ENGANCHE"}
    ]
    plan.proposed_state_writes.extend(
        [
            DinamoAgentStateWrite(field="CREDITO", value=credit, source="atendia_knowledge_base"),
            DinamoAgentStateWrite(field="ENGANCHE", value=down_payment, source="atendia_knowledge_base"),
        ]
    )
    for step in plan.tool_plan:
        if step.get("tool") == "quote":
            step.setdefault("input", {})["plan_code"] = down_payment
    previous = _as_list((plan.action_payload or {}).get("_tool_results"))
    plan.action_payload = {
        **plan.action_payload,
        "_tool_results": [*previous, {"tool": "resolve_credit_plan", "payload": payload}],
    }


async def _run_quote_tool(
    *,
    tenant_id: UUID | None,
    tool_dispatch: Any,
    model: Any,
    plan_code: Any,
) -> dict[str, Any]:
    result = await tool_dispatch.quote(
        tenant_id=tenant_id,
        candidate_queries=[str(model)],
        plan_code=str(plan_code) if plan_code else None,
        collection_ids=[],
    )
    payload = _tool_payload(result)
    return {**payload, "_tool_results": [{"tool": "quote", "payload": payload}]}


def _apply_state_write_policy(
    *,
    inbound_text: str,
    current_state: dict[str, Any],
    proposed_state_writes: list[DinamoAgentStateWrite],
) -> dict[str, list[DinamoAgentStateWrite]]:
    proposed_updates = {item.field: item.value for item in proposed_state_writes}
    if not proposed_updates:
        return {"accepted": [], "rejected": []}

    policy_result = apply_state_write_policy(
        StateWritePolicyRequest(
            current_state=current_state,
            proposed_updates=dict(proposed_updates),
            nlu_entities=dict(proposed_updates),
            turn_context={
                "inbound_text": inbound_text,
                "pipeline": None,
                "allow_model_change_overwrite": True,
            },
        )
    )
    blocked_fields = {str(item.get("field")) for item in policy_result.blocked_updates}
    source_by_field = {item.field: item.source for item in proposed_state_writes}
    accepted = [
        DinamoAgentStateWrite(field=field, value=value, source=source_by_field.get(field, "agent_brain"))
        for field, value in policy_result.approved_updates.items()
        if field not in blocked_fields
    ]
    rejected = [
        DinamoAgentStateWrite(
            field=str(item.get("field")),
            value=item.get("attempted_value"),
            source=source_by_field.get(str(item.get("field")), "state_write_policy"),
            reason=str(item.get("reason") or "blocked_by_state_write_policy"),
        )
        for item in policy_result.blocked_updates
    ]
    return {"accepted": accepted, "rejected": rejected}


def _merge_state(
    current_state: dict[str, Any],
    accepted_writes: list[DinamoAgentStateWrite],
) -> dict[str, Any]:
    merged = dict(current_state)
    for item in accepted_writes:
        existing = merged.get(item.field)
        if isinstance(existing, dict) and "value" in existing:
            updated = dict(existing)
            updated["value"] = item.value
            updated["source"] = item.source
            merged[item.field] = updated
        else:
            merged[item.field] = {"value": item.value, "source": item.source}
    return merged


def _message_text(inbound_message: Any) -> str:
    if isinstance(inbound_message, str):
        return inbound_message.strip()
    if isinstance(inbound_message, dict):
        for key in ("text", "body", "content", "message"):
            value = inbound_message.get(key)
            if value:
                return str(value).strip()
    for key in ("text", "body", "content", "message"):
        value = getattr(inbound_message, key, None)
        if value:
            return str(value).strip()
    return ""


def _tenant_id(tenant: Any) -> UUID | None:
    value = _maybe_attr(tenant, "id")
    if isinstance(value, UUID):
        return value
    if value:
        try:
            return UUID(str(value))
        except ValueError:
            return None
    return None


def _tenant_name(tenant: Any) -> str:
    for key in ("name", "display_name", "slug"):
        value = _maybe_attr(tenant, key)
        if value:
            return _normalize(value)
    return ""


def _maybe_attr(obj: Any, key: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def _config_flag_enabled(config: dict[str, Any] | None) -> bool:
    return _flag_status(config=config, settings=None)[0]


def _settings_flag_enabled(settings: Any | None) -> bool:
    return _truthy(getattr(settings, "dinamo_agent_first_enabled", None))


def _env_flag_enabled() -> bool:
    return _truthy(os.getenv("DINAMO_AGENT_FIRST_ENABLED")) or _truthy(
        os.getenv("ATENDIA_V2_DINAMO_AGENT_FIRST_ENABLED")
    )


def _flag_status(
    *,
    config: dict[str, Any] | None,
    settings: Any | None,
) -> tuple[bool, str | None]:
    if isinstance(config, dict):
        features = config.get("features")
        if isinstance(features, dict) and "dinamo_agent_first" in features:
            return _truthy(features.get("dinamo_agent_first")), "tenant_config.features"
        if "dinamo_agent_first" in config:
            return _truthy(config.get("dinamo_agent_first")), "tenant_config"
    if _settings_flag_enabled(settings):
        return True, "settings"
    if os.getenv("DINAMO_AGENT_FIRST_ENABLED") is not None:
        return _truthy(os.getenv("DINAMO_AGENT_FIRST_ENABLED")), "env.DINAMO_AGENT_FIRST_ENABLED"
    if os.getenv("ATENDIA_V2_DINAMO_AGENT_FIRST_ENABLED") is not None:
        return (
            _truthy(os.getenv("ATENDIA_V2_DINAMO_AGENT_FIRST_ENABLED")),
            "env.ATENDIA_V2_DINAMO_AGENT_FIRST_ENABLED",
        )
    return False, None


def _sandbox_or_canary_allowed(
    *,
    channel: str | None,
    test_run: str | None,
    inbound_metadata: dict[str, Any] | None,
) -> bool:
    normalized_channel = _normalize(channel)
    normalized_run = _normalize(test_run)
    if isinstance(inbound_metadata, dict) and _truthy(inbound_metadata.get("sandbox")):
        return True
    if "sandbox" in normalized_channel or "canary" in normalized_channel:
        return True
    if normalized_channel == "api_sandbox_real_path":
        return True
    return normalized_run.startswith("dinamo_agent_first_canary")


def _live_limited_allowed(
    *,
    config: dict[str, Any] | None,
    tenant_id: str | None,
    customer_id: str | None,
    customer_phone_e164: str | None,
) -> bool:
    if not isinstance(config, dict):
        return False
    raw = config.get("dinamo_agent_first_live_limited")
    if not isinstance(raw, dict):
        return False
    required_flags = (
        raw.get("enabled"),
        raw.get("allow_real_outbox"),
        raw.get("human_monitoring_active"),
        raw.get("rollback_ready"),
    )
    if not all(_truthy(value) for value in required_flags):
        return False

    allowed_tenants = _normalized_set(raw.get("allowed_tenant_ids"))
    if allowed_tenants and _normalize(tenant_id) not in allowed_tenants:
        return False

    allowed_contacts = _normalized_set(raw.get("allowed_contact_ids"))
    if customer_id and _normalize(customer_id) in allowed_contacts:
        return True

    allowed_phones = {_normalize_phone(item) for item in _as_list(raw.get("allowed_phone_numbers"))}
    allowed_phones.discard("")
    return bool(customer_phone_e164 and _normalize_phone(customer_phone_e164) in allowed_phones)


def _live_limited_restricts_to_allowlist(config: dict[str, Any] | None) -> bool:
    if not isinstance(config, dict):
        return False
    raw = config.get("dinamo_agent_first_live_limited")
    if not isinstance(raw, dict):
        return False
    return _truthy(raw.get("enabled")) and _truthy(raw.get("restrict_to_allowlist"))


def _normalized_set(value: Any) -> set[str]:
    return {_normalize(item) for item in _as_list(value) if _normalize(item)}


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if value is None:
        return []
    return [value]


def _normalize_phone(value: Any) -> str:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    return f"+{digits}" if digits else ""


def _mapping_value(mapping: dict[str, Any] | None, key: str) -> Any:
    if not isinstance(mapping, dict):
        return None
    return mapping.get(key)


def _first_text(*values: Any) -> str | None:
    for value in values:
        if value is None:
            continue
        text_value = str(value).strip()
        if text_value:
            return text_value
    return None


def _truthy(value: Any) -> bool:
    return str(value).strip().casefold() in {"1", "true", "yes", "on", "si", "sí"}


def _question_intents(normalized: str) -> list[str]:
    intents: list[str] = []
    if any(token in normalized for token in ("donde estan", "ubicacion", "direccion", "sucursal")):
        intents.append("ubicacion")
    if "buro" in normalized or "historial crediticio" in normalized:
        intents.append("buro")
    if any(token in normalized for token in ("liquidar", "liquido", "liquide", "pagar antes", "adelantar", "penalizacion")):
        intents.append("liquidacion")
    if any(
        token in normalized
        for token in (
            "cuanto sale",
            "cuanto cuesta",
            "cuanto vale",
            "cuanto es",
            "precio",
            "cotizacion",
            "cotizar",
            "cuanto queda",
        )
    ):
        intents.append("precio")
    if _is_document_question(normalized):
        intents.append("documentos")
    if any(token in normalized for token in ("francisco", "humano", "asesor", "persona")):
        intents.append("humano")
    return _dedupe(intents)


def _is_document_question(normalized: str) -> bool:
    if any(
        token in normalized
        for token in ("precio", "cuanto sale", "cuanto cuesta", "cuanto vale", "cuanto queda")
    ):
        return False
    return any(
        token in normalized
        for token in (
            "que documentos",
            "documentos",
            "papeles",
            "requisitos",
            "que mando",
            "mando primero",
            "que te mando",
            "ine",
            "ya te mande",
            "ya mande",
        )
    )


def _parse_seniority_months(normalized: str) -> int | None:
    if re.search(r"\b(un|una)\s*(ano|anio|aÃ±o)\b", normalized):
        return 12
    years = re.search(r"\b(\d{1,2})\s*(anos?|anios?|años?)\b", normalized)
    if years:
        return int(years.group(1)) * 12
    months = re.search(r"\b(\d{1,2})\s*mes(?:es)?\b", normalized)
    if months:
        return int(months.group(1))
    return None


def _income_plan(normalized: str) -> dict[str, str] | str | None:
    has_deposit = "deposit" in normalized or "tarjeta" in normalized
    has_nomina = "nomina" in normalized or "nómina" in normalized
    has_receipts = "recibo" in normalized
    if has_deposit and not has_nomina and not has_receipts:
        return "ambiguous"
    if (
        "por fuera" in normalized
        or "sin comprobantes" in normalized
        or "efectivo" in normalized
        or "no me dan recibos" in normalized
        or "no tengo recibos" in normalized
        or "sin recibos" in normalized
    ):
        return {"credit": "Sin Comprobantes", "down_payment": "20%"}
    if has_nomina and has_receipts:
        return {"credit": "Nomina Recibos", "down_payment": "15%"}
    if has_nomina and ("tarjeta" in normalized or "deposit" in normalized or normalized in {"es nomina", "nomina"}):
        return {"credit": "Nomina Tarjeta", "down_payment": "10%"}
    if "pension" in normalized:
        return {"credit": "Pensionados", "down_payment": "10%"}
    if "sat" in normalized or "facturo" in normalized or "negocio registrado" in normalized:
        return {"credit": "Negocio SAT", "down_payment": "15%"}
    if "guardia" in normalized or "seguridad" in normalized or "vigilante" in normalized:
        return {"credit": "Guardia de Seguridad", "down_payment": "30%"}
    return None


def _price_mentions_model(normalized: str) -> bool:
    if not any(token in normalized for token in ("cuanto", "precio", "cotiz", "cuesta", "queda")):
        return False
    modelish = normalized
    for token in ("cuanto", "cuesta", "queda", "precio", "cotizacion", "cotizar", "sale"):
        modelish = modelish.replace(token, " ")
    tokens = [
        token
        for token in modelish.split()
        if token not in {"la", "el", "una", "un", "esa", "ese", "de", "a", "credito"}
    ]
    return bool(tokens)


def _is_generic_credit_purchase(normalized: str) -> bool:
    if not any(token in normalized for token in ("credito", "financiamiento", "pagos")):
        return False
    if not any(token in normalized for token in ("moto", "motocicleta")):
        return False
    return not _contains_model_hint(normalized)


def _contains_model_hint(normalized: str) -> bool:
    return any(
        token in normalized
        for token in ("adventure", "r4", "urban", "urbana", "cargo", "heavy", "motocarro", "trabajo")
    )


def _is_document_status_question(normalized: str) -> bool:
    return any(
        token in normalized
        for token in (
            "ya te mande",
            "ya mande",
            "no me aparece",
            "si llego",
            "llego?",
            "se mando",
            "se envio",
            "te llego",
        )
    )


def _is_closing_ack(normalized: str) -> bool:
    return any(
        token in normalized
        for token in (
            "gracias",
            "perfecto",
            "ok voy",
            "hoy paso",
            "voy para alla",
            "manana paso",
            "mañana paso",
        )
    )


def _is_visit_closing(normalized: str) -> bool:
    return any(token in normalized for token in ("hoy paso", "voy para alla", "manana paso", "mañana paso"))


def _is_ambiguous_income_followup(normalized: str) -> bool:
    return any(
        token in normalized
        for token in (
            "no se si cuenta como nomina",
            "no se si es nomina",
            "cuenta como nomina",
            "no estoy seguro si es nomina",
        )
    )


def _dual_income_ambiguous(normalized: str) -> bool:
    if "dos trabajos" in normalized or "dos ingresos" in normalized:
        return True
    return ("deposit" in normalized or "nomina" in normalized) and "por fuera" in normalized


def _price_objection(normalized: str) -> bool:
    return any(token in normalized for token in ("esta caro", "muy caro", "se me hace caro"))


def _is_payment_support_request(normalized: str) -> bool:
    if any(token in normalized for token in ("liquid", "adelant", "penalizacion", "pagar antes", "abonar")):
        return False
    if any(
        token in normalized
        for token in (
            "quiero hacer un pago",
            "hacer un pago",
            "quiero pagar",
            "pagar mi mensualidad",
            "pago de mi mensualidad",
            "mensualidad",
            "donde deposito",
            "deposito?",
            "separar",
            "separado",
            "apartar",
            "aparto",
        )
    ):
        return True
    return "pago" in normalized and not any(
        token in normalized for token in ("pago quincenal", "cuanto", "precio", "enganche")
    )


def _is_document_attachment_followup(normalized: str, history: list[tuple[str, str]]) -> bool:
    if not any(token in normalized for token in ("que hago", "como le hago", "entonces")):
        return False
    previous_bot = " ".join(
        str(text or "")
        for role, text in history[-4:]
        if str(role).lower() in {"outbound", "bot", "assistant"}
    ).casefold()
    return "foto o archivo" in previous_bot and (
        "no lo cuento como recibido" in previous_bot or "no me aparece cargado" in previous_bot
    )


def _has_quote_context(state: dict[str, Any]) -> bool:
    return bool(_state_value(state, "last_quote") or _state_value(state, "MOTO") and _state_value(state, "ENGANCHE"))


def _last_quote_payload(state: dict[str, Any]) -> dict[str, Any] | None:
    value = _state_value(state, "last_quote")
    if isinstance(value, dict) and value.get("status") == "ok":
        return dict(value)
    return None


def _public_quote_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in dict(payload).items()
        if key != "_tool_results"
    }


def _ask_model_with_recent_candidates(state: dict[str, Any]) -> str:
    candidates = _state_value(state, "recent_catalog_candidates")
    if isinstance(candidates, list) and candidates:
        return _candidate_options_text(candidates)
    return "Ya tengo tu plan, solo dime cual modelo quieres cotizar."


def _candidate_options_text(candidates: list[dict[str, Any]]) -> str:
    names = [
        str(item.get("name") or "").strip()
        for item in candidates[:3]
        if isinstance(item, dict) and str(item.get("name") or "").strip()
    ]
    if not names:
        return "Ya tengo tu plan, solo dime cual modelo quieres cotizar."
    if len(names) == 1:
        return f"Te refieres a {names[0]}? Confirmame ese modelo para darte precio exacto."
    return "Tengo estas opciones: " + ", ".join(names) + ". Cual quieres cotizar?"


def _auto_select_catalog_candidate(
    *,
    inbound_text: str,
    current_state: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> str | None:
    normalized = _normalize(inbound_text)
    if _state_value(current_state, "recent_catalog_candidates"):
        return None
    if not any(token in normalized for token in ("urban", "urbana")):
        return None
    if any(token in normalized for token in ("trabajo", "cargo", "carga", "heavy", "motocarro")):
        return None
    for item in candidates:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        sku = _normalize(item.get("sku"))
        if name and (sku == "u2_150_cc" or _normalize(name).startswith("u2 ")):
            return name
    return None


def _document_status_text(normalized: str) -> str:
    if _mentions_ine_front(normalized):
        return "Me falta la parte de atras de la INE. Mandamela como foto o archivo y reviso que sigue."
    if "no me aparece" in normalized:
        return (
            "No aparece cargado de mi lado todavia. Para no marcarla como recibida sin archivo, "
            "mandamela otra vez como foto o archivo."
        )
    return "No me aparece cargado todavia. Mandamelo otra vez como foto o archivo y te confirmo cuando entre."


def _is_no_attachment_document_ack(normalized: str) -> bool:
    return any(
        token in normalized
        for token in (
            "no trae adjunto",
            "sin adjunto",
            "sin archivo",
            "no tiene adjunto",
            "no se adjunto",
            "no aparece adjunto",
        )
    )


def _document_request_text(normalized: str) -> str:
    if _mentions_ine_front(normalized):
        return "Me falta la parte de atras de la INE. Mandamela como foto o archivo y reviso que sigue."
    return "Para seguir, mandame tu INE por ambos lados y comprobante de domicilio reciente si aplica a tu plan."


def _mentions_ine_front(normalized: str) -> bool:
    return "ine" in normalized and any(token in normalized for token in ("frente", "delantera", "parte de enfrente"))


def _asks_more_down_payment(normalized: str) -> bool:
    return any(
        token in normalized
        for token in (
            "mas enganche",
            "mayor enganche",
            "subir enganche",
            "subo enganche",
            "aumentar enganche",
            "aumento enganche",
            "dar mas de enganche",
            "darle mas enganche",
        )
    )


def _recent_candidate_match(normalized: str, state: dict[str, Any]) -> str | None:
    candidates = _state_value(state, "recent_catalog_candidates")
    if not isinstance(candidates, list) or not candidates:
        return None

    ordinal_map = {
        "primera": 0,
        "primer": 0,
        "1": 0,
        "uno": 0,
        "segunda": 1,
        "segundo": 1,
        "2": 1,
        "dos": 1,
        "tercera": 2,
        "tercero": 2,
        "3": 2,
        "tres": 2,
    }
    tokens = set(normalized.split())
    for token, index in ordinal_map.items():
        if token in tokens and index < len(candidates):
            name = str(candidates[index].get("name") or "").strip()
            if name:
                return name

    request_tokens = {
        token
        for token in re.findall(r"[a-z0-9]+", normalized)
        if token
        not in {
            "la",
            "el",
            "una",
            "un",
            "esa",
            "ese",
            "mejor",
            "prefiero",
            "entonces",
            "cuanto",
            "queda",
            "sale",
            "precio",
            "cotiza",
            "cotizar",
        }
    }
    broad_tokens = {"urban", "urbana", "trabajo", "cargo", "carga", "heavy", "motocarro", "moto", "modelo"}

    for item in candidates:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        sku = str(item.get("sku") or "").strip()
        if not name:
            continue
        haystack = _model_match_tokens(name, sku)
        meaningful_overlap = (request_tokens - broad_tokens) & haystack
        if meaningful_overlap:
            return name
        short_codes = {token for token in haystack if re.search(r"[a-z]+\d+|\d+[a-z]+", token)}
        if short_codes & request_tokens:
            return name
    return None


def _model_selected_writes(model: str) -> list[DinamoAgentStateWrite]:
    return [
        DinamoAgentStateWrite(
            field="MOTO",
            value=model,
            source="agent_brain",
            reason="recent_catalog_candidate_selected",
        ),
        DinamoAgentStateWrite(
            field="recent_catalog_candidates",
            value=[],
            source="agent_brain",
            reason="model_selected_clear_candidates",
        ),
    ]


def _should_keep_recent_candidates(normalized: str, state: dict[str, Any]) -> bool:
    candidates = _state_value(state, "recent_catalog_candidates")
    if not isinstance(candidates, list) or not candidates:
        return False
    if _recent_candidate_match(normalized, state):
        return False
    broad_category = any(
        token in normalized
        for token in ("urban", "urbana", "cargo", "carga", "trabajo", "heavy", "motocarro")
    )
    if not broad_category:
        return False
    explicit_modelish = any(
        re.search(pattern, normalized)
        for pattern in (
            r"\badventure\b",
            r"\br4\b",
            r"\bu2\b",
            r"\bu5\b",
            r"\b[a-z]+\d+\b",
            r"\b\d+[a-z]+\b",
        )
    )
    return not explicit_modelish


def _model_match_tokens(name: str, sku: str) -> set[str]:
    raw = " ".join(part for part in (_normalize(name), _normalize(sku).replace("_", " ").replace("-", " ")) if part)
    tokens = set(re.findall(r"[a-z0-9]+", raw))
    collapsed = re.sub(r"[^a-z0-9]", "", raw)
    if collapsed:
        tokens.add(collapsed)
    for match in re.findall(r"\b([a-z]+)\s*(\d+)\b|\b(\d+)\s*([a-z]+)\b", raw):
        pieces = [part for part in match if part]
        if len(pieces) == 2:
            tokens.add("".join(pieces))
    return tokens


def _source_metadata_from_tool_results(
    tool_results: list[dict[str, Any]],
    action_payload: dict[str, Any],
) -> dict[str, Any]:
    keys = {
        "quote_source",
        "catalog_source",
        "requirements_source",
        "faq_source",
        "tenant_id",
        "knowledge_version",
        "catalog_version",
        "requirements_version",
        "faq_version",
        "local_downloads_source",
        "fake_deterministic_tools",
    }
    metadata: dict[str, Any] = {}
    candidates = [action_payload, *[item.get("payload") for item in tool_results if isinstance(item, dict)]]
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        for key in keys:
            if key not in metadata and key in candidate:
                metadata[key] = candidate[key]
        source = candidate.get("source")
        if isinstance(source, dict):
            for key in keys:
                if key not in metadata and key in source:
                    metadata[key] = source[key]
    return metadata


def _resume_after_faq(*, plan: _AgentPlan, current_state: dict[str, Any]) -> str:
    if _state_value(current_state, "last_quote") or (
        _state_value(current_state, "MOTO") and _state_value(current_state, "ENGANCHE")
    ):
        return "Seguimos con la cotizacion que ya tienes; si quieres avanzar, vemos documentos."
    if plan.primary_intent == "ubicacion":
        if _state_value(current_state, "MOTO") and not _state_value(current_state, "CREDITO"):
            return "Y seguimos con esa moto; dime como recibes tus ingresos para cotizarla bien."
        if _state_value(current_state, "MOTO"):
            return "Y seguimos con esa moto."
        return ""
    if plan.primary_intent == "buro":
        if _state_value(current_state, "MOTO") and not _state_value(current_state, "CREDITO"):
            return "Y seguimos con esa moto; dime como recibes tus ingresos para cotizarla bien."
        return "Para avanzar, dime que modelo tienes en mente."
    if plan.primary_intent == "liquidacion":
        return "Si quieres, seguimos revisando la opcion que te interesa."
    return ""


def _quote_draft_text(payload: dict[str, Any]) -> str:
    if not isinstance(payload, dict) or payload.get("status") != "ok":
        return "No alcanzo a cotizarla todavia; confirmame el modelo y el plan para revisarlo bien."
    name = payload.get("name") or "la moto"
    cash = payload.get("cash_price_mxn") or payload.get("list_price_mxn")
    option = {}
    payment_options = payload.get("payment_options")
    requested = str(payload.get("requested_plan_code") or "").strip()
    if isinstance(payment_options, dict):
        if requested and isinstance(payment_options.get(requested), dict):
            option = payment_options[requested]
        else:
            option = next((item for item in payment_options.values() if isinstance(item, dict)), {})
    down = option.get("down_payment_mxn") or option.get("enganche_mxn")
    payment = (
        option.get("installment_mxn")
        or option.get("pago_quincenal_mxn")
        or option.get("payment_mxn")
        or option.get("biweekly_payment_mxn")
    )
    term = option.get("plazo_texto") or option.get("term_label") or option.get("term") or option.get("term_count")
    parts = []
    if cash:
        parts.append(f"La {name} de contado esta en ${int(cash):,}.")
    credit_details = []
    if down:
        credit_details.append(f"Enganche: ${int(down):,}.")
    if payment:
        credit_details.append(f"Pago quincenal: ${int(payment):,}.")
    if term:
        credit_details.append(f"Plazo: {_term_text(term)}.")
    if credit_details:
        plan_label = f" con tu plan del {requested}" if requested else ""
        parts.append(f"A credito{plan_label}:")
        parts.extend(credit_details)
    return "\n".join(parts) or f"Ya tengo la {name}; te reviso el plan para cotizarla bien."


def _looks_like_model_request(normalized: str) -> bool:
    if "moto" in normalized or "modelo" in normalized:
        return True
    if any(token in normalized for token in ("urban", "urbana", "cargo", "trabajo", "heavy", "motocarro")):
        return True
    tokens = normalized.split()
    if not tokens or len(tokens) > 5:
        return False
    stopwords = {
        "la",
        "el",
        "una",
        "un",
        "quiero",
        "busco",
        "me",
        "interesa",
        "mejor",
        "prefiero",
        "entonces",
        "esa",
        "ese",
    }
    candidate_tokens = [token for token in tokens if token not in stopwords]
    if not candidate_tokens:
        return False
    has_short_model_code = any(any(ch.isdigit() for ch in token) for token in candidate_tokens)
    has_article_hint = tokens[0] in {"la", "el", "una", "un", "esa", "ese"}
    has_buy_hint = bool(set(tokens) & {"quiero", "busco", "interesa", "mejor", "prefiero", "entonces"})
    return has_short_model_code or (has_article_hint and len(candidate_tokens[0]) >= 3) or has_buy_hint


def _term_text(term: Any) -> str:
    if isinstance(term, int):
        return f"{term} quincenas"
    text = str(term).strip()
    if text.isdigit():
        return f"{text} quincenas"
    return text


def _faq_answer_text(
    *,
    normalized: str,
    plan: _AgentPlan,
    payload: dict[str, Any],
) -> str:
    if plan.primary_intent == "buro" and any(
        token in normalized for token in ("mal buro", "detalle en buro", "traigo buro", "debo", "deuda")
    ):
        return "Si, se revisa. Si el detalle es menor a $50,000 puede aplicar, sujeto a validacion."
    return str(payload.get("answer") or "").strip()


def _tool_payload(result: Any) -> dict[str, Any]:
    if isinstance(result, dict):
        return dict(result)
    payload = getattr(result, "action_payload", None)
    if isinstance(payload, dict):
        return dict(payload)
    if hasattr(result, "model_dump"):
        dumped = result.model_dump(mode="json")
        return dumped if isinstance(dumped, dict) else {}
    return {}


def _catalog_model_name(payload: dict[str, Any]) -> str | None:
    for item in _catalog_candidates(payload):
        if not isinstance(item, dict):
            continue
        name = item.get("name") or item.get("model") or item.get("title")
        if name and _catalog_model_name_looks_safe(str(name)):
            return str(name).strip()
    return None


def _catalog_candidates(payload: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[Any] = []
    for key in ("results", "items", "matches", "hits"):
        candidates.extend(_as_list(payload.get(key)))
    if not candidates and payload.get("name"):
        candidates.append(payload)

    normalized_candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in candidates:
        if not isinstance(item, dict):
            continue
        name = item.get("name") or item.get("model") or item.get("title")
        if not name or not _catalog_model_name_looks_safe(str(name)):
            continue
        candidate = {
            "name": str(name).strip(),
            "sku": item.get("sku"),
            "category": item.get("category"),
        }
        key = _normalize(candidate["sku"] or candidate["name"])
        if key in seen:
            continue
        seen.add(key)
        normalized_candidates.append(candidate)
    return normalized_candidates


def _catalog_model_name_looks_safe(value: str) -> bool:
    normalized = _normalize(value)
    if any(token in normalized for token in ("deposit", "nomina", "comprobante", "tarjeta")):
        return False
    return len(normalized.split()) >= 2 or bool(re.search(r"[a-z]+\d+|\d+[a-z]+|\d+\s*cc", normalized))


def _brand_facts(
    *,
    tenant: Any,
    customer: Any | None,
    config: dict[str, Any] | None,
    explicit: dict[str, Any] | None,
) -> dict[str, Any]:
    facts: dict[str, Any] = {
        "address": "Monterrey, Nuevo Leon",
        "buro_max_amount": "$50 mil",
    }
    if isinstance(config, dict):
        brand = config.get("brand_facts") or config.get("brand")
        if isinstance(brand, dict):
            facts.update(brand)
    if isinstance(explicit, dict):
        facts.update(explicit)
    name = _maybe_attr(tenant, "name")
    if name:
        facts.setdefault("tenant_name", name)
    customer_name = _maybe_attr(customer, "name")
    if customer_name:
        facts.setdefault("customer_name", customer_name)
    return facts


def _state_value(state: dict[str, Any], key: str) -> Any:
    value = state.get(key)
    if isinstance(value, dict) and "value" in value:
        return value.get("value")
    return value


def _present_state_slots(state: dict[str, Any]) -> set[str]:
    return {key for key, value in state.items() if _state_value(state, key) not in (None, "", [], {})}


def _write_to_dict(item: DinamoAgentStateWrite) -> dict[str, Any]:
    return {
        "field": item.field,
        "value": item.value,
        "source": item.source,
        "reason": item.reason,
    }


def _previous_bot_asked_documents(history: list[tuple[str, str]]) -> bool:
    document_re = re.compile(r"\b(ine|documentos?|papeles|comprobante)\b", re.IGNORECASE)
    return any(
        document_re.search(str(text or ""))
        for role, text in history[-6:]
        if str(role).lower() in {"outbound", "bot", "assistant"}
    )


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _normalize(value: Any) -> str:
    decomposed = unicodedata.normalize("NFKD", str(value or ""))
    ascii_value = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", ascii_value).casefold().strip()


def _dedupe(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = str(value or "").strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        out.append(cleaned)
    return out


__all__ = [
    "DINAMO_TENANT_NAMES",
    "DinamoAgentStateWrite",
    "DinamoAgentToolCall",
    "DinamoAgentTurnResult",
    "DinamoRuntimeSelection",
    "dinamo_agent_first_enabled",
    "dinamo_runtime_path",
    "select_dinamo_runtime",
    "run_dinamo_agent_turn",
]
