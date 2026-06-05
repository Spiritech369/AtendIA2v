from __future__ import annotations

# ruff: noqa: E501,I001

import asyncio
import argparse
import json
import time
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from atendia.agent_runtime.advisor_brain_contract import (
    AdvisorBrainContractValidator,
    advisor_brain_contract_system_rules,
    advisor_brain_decision_json_schema,
)
from atendia.agent_runtime.advisor_pipeline import AdvisorFirstAgentProvider
from atendia.agent_runtime.canonical import AliasMap, CanonicalProductReference
from atendia.agent_runtime.composer_quote_context import (
    build_quote_context,
    enforce_quote_context_on_message,
)
from atendia.agent_runtime.conversation_progress import (
    build_conversation_progress_context,
    conversation_progress_memory,
    latest_customer_act,
)
from atendia.agent_runtime.policy_validator import PolicyValidator
from atendia.agent_runtime.provider_reliability import (
    ProviderEmptyResponseError,
    ProviderMalformedJSONError,
    ProviderReliabilityConfig,
    ProviderReliabilityLayer,
    ProviderRetryExhaustedError,
    classify_provider_error,
    reset_provider_reliability_circuits,
)
from atendia.agent_runtime.quote_safety import visible_quote_signal
from atendia.agent_runtime.schemas import (
    AdvisorBrainDecision,
    AdvisorBrainToolRequest,
    ToolExecutionResult,
    TurnContext,
    TurnOutput,
)
from atendia.agent_runtime.state_writer import StateWriteResult
from atendia.config import get_settings
from atendia.simulation.dinamo_openai_common import payload_hash
from atendia.simulation.advisor_first_multiturn import (
    ALLOWED_STAGES,
    REPORT_DIR,
    VISIBLE_FIELDS,
    CustomerTurn,
    DinamoToolLayer,
    SimulationCaseSpec,
    _apply_output_to_state,
    _context_for_turn,
    _current_product_ref,
    _document_field_updates,
    _documents_from_tools,
    _hard_failures,
    _last_quote_from_output,
    _lifecycle_from_context,
    _remember_options,
    _repetition_detected,
    dinamo_products,
    fold,
    simulation_cases,
    tenant_config,
)
from atendia.simulation.advisor_first_multiturn import (
    run_simulation as run_local_simulation,
)

PROVIDER_REPORT_MD = REPORT_DIR / "provider_advisor_first_eval.md"
PROVIDER_REPORT_JSON = REPORT_DIR / "provider_advisor_first_eval.json"
COMPARISON_MD = REPORT_DIR / "provider_vs_local_comparison.md"
ROBOTIC_AUDIT_MD = REPORT_DIR / "robotic_phrase_audit.md"
STALE_QUOTE_AUDIT_MD = REPORT_DIR / "stale_quote_audit.md"
REPETITION_AUDIT_MD = REPORT_DIR / "provider_repetition_audit.md"
REPETITION_AUDIT_JSON = REPORT_DIR / "provider_repetition_audit.json"


@dataclass
class ProviderTurnAudit:
    turn_index: int
    customer_message: str
    attachments: list[dict[str, Any]]
    provider_used: str
    raw_model_decision: dict[str, Any] | str | None
    raw_model_composer: dict[str, Any] | str | None
    advisor_decision: dict[str, Any]
    tool_calls: list[dict[str, Any]]
    state_updates: list[dict[str, Any]]
    blocked_updates: list[dict[str, Any]]
    final_message: str
    quote_snapshot_id: str | None
    quote_snapshot_hash: str | None
    quote_safety: dict[str, Any]
    conversation_progress_guard: dict[str, Any]
    provider_reliability: dict[str, Any]
    previous_assistant_message: str
    quote_context_notes: list[str]
    robotic_phrase_score: int
    repeated_question_detected: bool
    stale_quote_detected: bool
    human_review_notes: list[str]
    model_emitted_internal_error_notes: list[str]
    pipeline_stage: str
    hard_validation_failures: list[str]


@dataclass
class ProviderCaseAudit:
    case_id: str
    title: str
    source: str
    pass_fail: str
    transcript: list[dict[str, str]]
    turns: list[ProviderTurnAudit]
    final_pipeline_stage: str
    naturalidad_score: float
    repeated_question_detected: bool
    stale_quote_detected: bool
    robotic_phrase_score: float
    failures: list[str]
    human_review_notes: list[str] = field(default_factory=list)


@dataclass
class ProviderConversationState:
    fields: dict[str, Any] = field(default_factory=dict)
    stage: str = "nuevos"
    documents: dict[str, Any] = field(default_factory=dict)
    summary: str = ""
    last_pending_question: str | None = None
    last_options: list[CanonicalProductReference] = field(default_factory=list)
    conversation_progress: dict[str, Any] = field(default_factory=dict)
    transcript: list[dict[str, str]] = field(default_factory=list)
    quote_phrase_count: int = 0
    quote_response_count: int = 0


class OpenAIAdvisorBrain:
    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        products: list[Any],
        circuit_scope: str | None = None,
    ) -> None:
        from openai import AsyncOpenAI

        self._reliability_config = _provider_reliability_config()
        self._client = AsyncOpenAI(
            api_key=api_key,
            max_retries=0,
            timeout=self._reliability_config.timeout_s,
        )
        self._model = model
        self._products = products
        self._circuit_scope = circuit_scope

    async def decide(self, context: TurnContext) -> AdvisorBrainDecision:
        payload = _advisor_brain_payload(context, self._products)
        t0 = time.perf_counter()
        try:
            raw_payload, reliability = await _chat_json_with_reliability(
                self._client,
                model=self._model,
                tenant_id=_provider_eval_circuit_tenant_id(
                    context.tenant_id,
                    self._circuit_scope,
                ),
                component="advisor_brain",
                messages=[
                    {"role": "system", "content": _advisor_brain_system_prompt()},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
                json_schema=advisor_brain_decision_json_schema(),
                temperature=0,
                reliability_config=self._reliability_config,
            )
            decision, parse_notes = _parse_advisor_decision_lenient(raw_payload)
        except Exception as exc:
            reliability = _fallback_reliability_snapshot(exc)
            return AdvisorBrainDecision(
                understanding="Provider call failed before AdvisorBrain decision could be completed.",
                customer_goal="human_review",
                conversation_goals=["handoff"],
                known_facts=context.memory.salient_facts,
                missing_facts=[],
                next_best_action="handoff",
                required_tools=[],
                proposed_state_changes=[],
                response_plan="Ask a human to review because provider timed out.",
                confidence=0.0,
                needs_human=True,
                risk_flags=["provider_timeout_or_error"],
                metadata={
                    "provider_used": "openai_advisor_brain",
                    "model": self._model,
                    "latency_ms": int((time.perf_counter() - t0) * 1000),
                    "raw_model_decision": None,
                    "provider_error_type": type(exc).__name__,
                    "provider_reliability": reliability,
                },
            )
        contract = AdvisorBrainContractValidator().normalize(context=context, decision=decision)
        decision = contract.decision
        return decision.model_copy(
            update={
                "metadata": {
                    **decision.metadata,
                    "provider_used": "openai_advisor_brain",
                    "model": self._model,
                    "latency_ms": int((time.perf_counter() - t0) * 1000),
                    "raw_model_decision": raw_payload,
                    "parse_notes": parse_notes,
                    "contract_violations": contract.violations,
                    "contract_warnings": contract.warnings,
                    "provider_reliability": reliability,
                }
            }
        )


class ProviderEvalToolLayer(DinamoToolLayer):
    def __init__(self, products: list[Any]) -> None:
        super().__init__(products)
        self._eval_products = products
        self._eval_aliases = AliasMap.from_products(products)

    async def execute(self, *, context: TurnContext, decision: AdvisorBrainDecision) -> list[ToolExecutionResult]:
        requests: list[AdvisorBrainToolRequest] = []
        for request in decision.required_tools:
            if request.name == "handoff.create":
                requests.append(request.model_copy(update={"name": "handoff.request"}))
            else:
                requests.append(request)
        normalized = decision.model_copy(
            update={"required_tools": [_normalize_tool_request(context, tool) for tool in requests]}
        )
        return await super().execute(context=context, decision=normalized)

    def _catalog_lookup(self, request: AdvisorBrainToolRequest) -> ToolExecutionResult:
        ref = _coerce_product_ref(request.payload.get("canonical_product_ref"), self._eval_aliases)
        if ref:
            return ToolExecutionResult(
                tool_name=request.name,
                status="succeeded",
                data={"canonical_product_ref": ref.model_dump(mode="json")},
            )
        query = str(request.payload.get("query") or request.payload.get("product") or "")
        ref = _coerce_product_ref(query, self._eval_aliases)
        if ref:
            return ToolExecutionResult(
                tool_name=request.name,
                status="succeeded",
                data={"canonical_product_ref": ref.model_dump(mode="json")},
            )
        if "barata" in fold(query):
            work = next((product for product in self._eval_products if product.sku == "WORK-200"), None)
            if work:
                return ToolExecutionResult(
                    tool_name=request.name,
                    status="succeeded",
                    data={"canonical_product_ref": work.ref().model_dump(mode="json")},
                )
        return ToolExecutionResult(
            tool_name=request.name,
            status="succeeded",
            data={"options": [product.ref().model_dump(mode="json") for product in self._eval_products[:3]]},
        )

    def _quote_resolve(self, context: TurnContext, request: AdvisorBrainToolRequest) -> ToolExecutionResult:
        ref = _coerce_product_ref(request.payload.get("product"), self._eval_aliases)
        if ref is None:
            ref = _current_product_ref(context.memory.salient_facts)
        if ref is None:
            return ToolExecutionResult(
                tool_name=request.name,
                status="blocked",
                data={"reason": "canonical_product_required"},
            )
        safe_request = request.model_copy(
            update={
                "payload": {
                    **request.payload,
                    "product": ref.model_dump(mode="json"),
                    "plan_code": request.payload.get("plan_code") or context.memory.salient_facts.get("Plan_Credito") or "cash",
                }
            }
        )
        try:
            return super()._quote_resolve(context, safe_request)
        except Exception as exc:
            return ToolExecutionResult(
                tool_name=request.name,
                status="failed",
                data={"reason": "quote_resolver_error"},
                error=type(exc).__name__,
            )


class OpenAIAdvisorComposer:
    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        circuit_scope: str | None = None,
    ) -> None:
        from openai import AsyncOpenAI

        self._reliability_config = _provider_reliability_config()
        self._client = AsyncOpenAI(
            api_key=api_key,
            max_retries=0,
            timeout=self._reliability_config.timeout_s,
        )
        self._model = model
        self._circuit_scope = circuit_scope

    async def compose(
        self,
        *,
        context: TurnContext,
        decision: AdvisorBrainDecision,
        tool_results: list[ToolExecutionResult],
        state_write_result: StateWriteResult,
        policy_warnings: list[dict[str, str]],
    ) -> TurnOutput:
        doc_results = _documents_from_tools(tool_results)
        quote = _quote_from_tool_results(tool_results)
        quote_context = build_quote_context(context=context, tool_results=tool_results)
        conversation_progress_context = build_conversation_progress_context(context)
        payload = {
            "customer_message": context.inbound_text,
            "conversation_history": [message.model_dump(mode="json") for message in context.messages[-8:]],
            "memory": context.memory.model_dump(mode="json"),
            "lifecycle": context.lifecycle.model_dump(mode="json"),
            "advisor_decision": decision.model_dump(mode="json"),
            "tool_results": [result.model_dump(mode="json") for result in tool_results],
            "quote_context": quote_context.to_payload(),
            "conversation_progress_context": conversation_progress_context.to_payload(),
            "state_writer": {
                "accepted": state_write_result.accepted,
                "blocked": state_write_result.blocked,
                "field_updates": [update.model_dump(mode="json") for update in state_write_result.field_updates],
            },
            "policy_warnings": policy_warnings,
            "rules": {
                "do_not_invent_quotes": True,
                "valid_quote_snapshot_present": bool(quote),
                "quote_block_is_deterministic": True,
                "customer_visible_copy_authority": "TurnOutput.final_message",
            },
        }
        t0 = time.perf_counter()
        model_response_succeeded = True
        try:
            raw_payload, reliability = await _chat_json_with_reliability(
                self._client,
                model=self._model,
                tenant_id=_provider_eval_circuit_tenant_id(
                    context.tenant_id,
                    self._circuit_scope,
                ),
                component="composer",
                messages=[
                    {"role": "system", "content": _composer_system_prompt()},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
                json_schema=_composer_output_json_schema(),
                temperature=0.2,
                reliability_config=self._reliability_config,
            )
        except Exception as exc:
            model_response_succeeded = False
            reliability = _fallback_reliability_snapshot(exc)
            raw_payload = {
                "final_message": _deterministic_composer_fallback_message(context, quote_context, tool_results),
                "human_review_notes": [f"composer_provider_error:{type(exc).__name__}"],
                "used_quote_snapshot_id": None,
                "used_quote_snapshot_hash": None,
            }
        message = str(raw_payload.get("final_message") or "").strip()
        if not message:
            message = "Necesito revisar esto con el equipo para responderte con certeza."
        message, quote_context_notes = enforce_quote_context_on_message(
            message=message,
            quote_context=quote_context,
            context=context,
        )
        trace = {
            "provider": "openai_advisor_first_pipeline",
            "provider_used": "openai",
            "model": self._model,
            "latency_ms": int((time.perf_counter() - t0) * 1000),
            "architecture": [
                "context_builder",
                "advisor_brain_gpt",
                "tool_layer",
                "policy_validation",
                "state_update_proposal",
                "composer_gpt",
            ],
            "advisor_brain": decision.model_dump(mode="json"),
            "raw_model_decision": decision.metadata.get("raw_model_decision"),
            "raw_model_composer": raw_payload,
            "tool_results": [result.model_dump(mode="json") for result in tool_results],
            "quote_context": quote_context.to_payload(),
            "quote_context_notes": quote_context_notes,
            "conversation_progress_context": conversation_progress_context.to_payload(),
            "used_quote_snapshot_id": raw_payload.get("used_quote_snapshot_id"),
            "used_quote_snapshot_hash": raw_payload.get("used_quote_snapshot_hash"),
            "state_writer": {"accepted": state_write_result.accepted, "blocked": state_write_result.blocked},
            "policy_warnings": policy_warnings,
            "human_review_notes": _trusted_composer_human_review_notes(
                raw_payload,
                model_response_succeeded=model_response_succeeded,
            ),
            "model_emitted_internal_error_notes": _model_emitted_internal_error_notes(
                raw_payload,
                model_response_succeeded=model_response_succeeded,
            ),
            "component_provider_reliability": {
                "advisor_brain": decision.metadata.get("provider_reliability") or {},
                "composer": reliability,
            },
            "provider_reliability": {
                "advisor_brain": decision.metadata.get("provider_reliability") or {},
                "composer": reliability,
            },
        }
        return TurnOutput(
            final_message=message,
            field_updates=state_write_result.field_updates + _document_field_updates(context, doc_results),
            lifecycle_update=_lifecycle_from_context(context, decision, quote, doc_results, state_write_result),
            confidence=decision.confidence,
            needs_human=decision.needs_human,
            risk_flags=list(decision.risk_flags),
            trace_metadata=trace,
        )


async def _chat_json_with_reliability(
    client: Any,
    *,
    model: str,
    tenant_id: str,
    component: str,
    messages: list[dict[str, str]],
    json_schema: dict[str, Any],
    temperature: float,
    reliability_config: ProviderReliabilityConfig,
) -> tuple[dict[str, Any], dict[str, Any]]:
    reliability = ProviderReliabilityLayer(
        provider=f"openai:{component}",
        model=model,
        tenant_id=tenant_id,
        config=reliability_config,
    )

    async def operation() -> dict[str, Any]:
        response = await client.chat.completions.create(
            model=model,
            messages=messages,
            response_format={"type": "json_schema", "json_schema": json_schema},
            temperature=temperature,
        )
        raw_text = response.choices[0].message.content or ""
        if not raw_text.strip():
            raise ProviderEmptyResponseError(f"empty {component} response")
        try:
            raw = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise ProviderMalformedJSONError(f"malformed {component} JSON") from exc
        if not isinstance(raw, dict):
            raise ProviderMalformedJSONError(f"{component} JSON must be an object")
        return raw

    try:
        raw_payload = await reliability.execute(
            operation,
            operation_name=component,
            idempotency_key=f"{tenant_id}:{component}:{payload_hash({'messages': messages})}",
        )
        return raw_payload, reliability.snapshot().to_dict()
    except Exception as exc:
        reliability.record_fallback_response()
        exc.provider_reliability_snapshot = reliability.snapshot().to_dict()
        raise


def adversarial_cases() -> list[SimulationCaseSpec]:
    specs: list[SimulationCaseSpec] = []
    raw_cases = [
        ("adv_01", "Typo Adventure buro precio", ["ola kiero la adventur cuanto y tengo buro", "trabajo ase 2 anos", "me pagan x fuera", "ok", "docs?"]),
        ("adv_02", "Audio transcrito R4", ["audio: me intereza erre cuatro creo precio credito", "tengo quince anios en el jale", "me pagan cash por fuera", "cotizame esa", "va"]),
        ("adv_03", "Cambia dos veces", ["Quiero la Adventure", "Cotizame", "Mejor la U5", "No, ahora la R4", "Cuanto queda?"]),
        ("adv_04", "Esa no la otra", ["Ensename opciones", "La primera", "esa no, la otra", "me pagan por fuera", "cotizala"]),
        ("adv_05", "Cuatro preguntas en un mensaje", ["Precio, ubicacion, documentos y buro para la R4", "15 anos trabajando", "por fuera", "cotiza", "que sigue"]),
        ("adv_06", "Ok ambiguo sin quote", ["Me gustan las motos de trabajo", "ok", "la barata", "tengo 1 ano", "por fuera"]),
        ("adv_07", "Documentos antes de cotizar", ["Te mando mi INE", "tambien comprobante", "quiero la U5", "de contado", "ya quedo?"]),
        ("adv_08", "Humano y sigue preguntando", ["Quiero un humano", "pero cuanto cuesta la Adventure?", "donde estan?", "tengo buro", "Francisco me puede hablar?"]),
        ("adv_09", "Nombre parcial la r", ["Me interesa la r", "la deportiva", "tengo 2 anos", "por fuera", "cotizame"]),
        ("adv_10", "Contradice ingreso", ["R4, me pagan por nomina", "no perdon, es por fuera", "tengo 4 anos", "cotiza", "ok"]),
        ("adv_11", "Contradice antiguedad", ["Adventure credito, tengo 6 meses", "no, llevo 3 anos", "por fuera", "cotizame", "docs"]),
        ("adv_12", "Barata contado", ["Cual es la barata?", "de contado", "donde estan", "que papeles", "ok"]),
        ("adv_13", "Typos documentos", ["q dokumntos okupo pa credito", "la adventure", "me pagan x fuera", "llevo 2 anios", "cotizala"]),
        ("adv_14", "Ok despues de opciones", ["Dame opciones", "ok", "la u5", "contado", "va"]),
        ("adv_15", "Cambio despues de documentos", ["R4 por fuera", "tengo 2 anos", "te mando INE", "mejor Adventure", "cotizame"]),
        ("adv_16", "Audio mal transcrito humano", ["audio: pasame con fransisko porfa", "tambien quiero saber precio r4", "tengo 10 anos", "nomina", "gracias"]),
        ("adv_17", "Buró mezcla", ["Tengo buro malo, donde estan y que piden para la U5?", "contado no credito", "precio", "ok", "humano"]),
        ("adv_18", "Modelo ambiguo despues de quote", ["Adventure por fuera", "2 anos", "cotiza", "y la otra cuanto?", "la R4"]),
        ("adv_19", "Otra sin opciones recientes", ["quiero la otra", "dame opciones", "la segunda", "por fuera 1 ano", "cotiza"]),
        ("adv_20", "Documento real antes de modelo", ["Mando comprobante", "Mando INE", "quiero moto para trabajar", "la primera", "por fuera"]),
        ("adv_21", "Precio sin producto", ["cuanto sale?", "la adventure", "contado", "documentos?", "ok"]),
        ("adv_22", "Repite ok varias veces", ["R4 por fuera 2 anos", "cotizame", "ok", "ok", "si"]),
        ("adv_23", "Pide requisitos y cambia producto", ["Requisitos para Adventure", "mejor U5", "contado", "cuanto?", "docs"]),
        ("adv_24", "Nombre parcial adventure", ["la adventure", "precio y ubicacion", "por fuera", "2 anos", "cotizame"]),
        ("adv_25", "Typos U5", ["la u cinco de kontado", "presio?", "donde", "papeles?", "va"]),
        ("adv_26", "Contradice buró", ["Tengo buro", "bueno no se si tengo", "Adventure credito", "2 anos por fuera", "cotiza"]),
        ("adv_27", "Humano no vender", ["Necesito hablar con una persona", "no quiero cotizacion todavia", "solo requisitos", "Adventure", "gracias"]),
        ("adv_28", "Tres preguntas sin pedir datos primero", ["R4: precio, donde estan, documentos?", "tengo 1 ano", "nomina", "cotiza", "ok"]),
        ("adv_29", "Cambio U5 Adventure R4", ["U5 contado", "mejor Adventure", "no la R4", "contado", "confirmame"]),
        ("adv_30", "Audio confuso documentos", ["audio: ya mande papeles creo ine y recibo", "no tengo fotos aqui", "quiero la barata", "por fuera", "cotiza"]),
    ]
    attachment_turns = {
        "adv_07": {1: [{"kind": "ine", "filename": "ine_adv_07.jpg"}], 2: [{"kind": "comprobante_domicilio", "filename": "comp_adv_07.pdf"}]},
        "adv_15": {3: [{"kind": "ine", "filename": "ine_adv_15.jpg"}]},
        "adv_20": {1: [{"kind": "comprobante_domicilio", "filename": "comp_adv_20.pdf"}], 2: [{"kind": "ine", "filename": "ine_adv_20.jpg"}]},
    }
    for case_id, title, messages in raw_cases:
        turns = [
            CustomerTurn(message, attachments=attachment_turns.get(case_id, {}).get(index, []))
            for index, message in enumerate(messages, start=1)
        ]
        specs.append(SimulationCaseSpec(case_id, title, turns))
    return specs


def provider_eval_case_specs(
    case_ids: set[str] | None = None,
) -> list[tuple[SimulationCaseSpec, str]]:
    cases = [
        *[(spec, "base") for spec in simulation_cases()],
        *[(spec, "adversarial") for spec in adversarial_cases()],
    ]
    if not case_ids:
        return cases
    known = {spec.case_id for spec, _source in cases}
    unknown = sorted(case_ids - known)
    if unknown:
        raise ValueError(f"unknown provider eval case id(s): {', '.join(unknown)}")
    return [(spec, source) for spec, source in cases if spec.case_id in case_ids]


def _provider_eval_circuit_scope(case_id: str) -> str:
    return f"provider_eval:{case_id}"


def _provider_eval_circuit_tenant_id(tenant_id: str, circuit_scope: str | None) -> str:
    if not circuit_scope:
        return tenant_id
    return f"{tenant_id}:{circuit_scope}"


async def run_provider_eval(case_ids: set[str] | None = None) -> dict[str, Any]:
    reset_provider_reliability_circuits()
    settings = get_settings()
    if not settings.openai_api_key or settings.agent_runtime_v2_model_provider != "openai":
        raise RuntimeError("agent_runtime_v2 OpenAI provider is not configured")
    products = dinamo_products()
    cases = provider_eval_case_specs(case_ids)
    semaphore = asyncio.Semaphore(3)

    async def guarded_run(spec: SimulationCaseSpec, source: str) -> ProviderCaseAudit:
        async with semaphore:
            return await _run_provider_case(
                spec,
                source,
                products,
                settings.agent_runtime_v2_model,
                settings.openai_api_key,
            )

    audits = await asyncio.gather(*(guarded_run(spec, source) for spec, source in cases))
    local_payload = await run_local_simulation()
    payload = _provider_payload(audits, local_payload)
    _write_provider_reports(payload)
    return payload


async def _run_provider_case(
    spec: SimulationCaseSpec,
    source: str,
    products: list[Any],
    model: str,
    api_key: str,
    provider: AdvisorFirstAgentProvider | None = None,
) -> ProviderCaseAudit:
    state = ProviderConversationState()
    if provider is None:
        circuit_scope = _provider_eval_circuit_scope(spec.case_id)
        provider = AdvisorFirstAgentProvider(
            advisor_brain=OpenAIAdvisorBrain(
                model=model,
                api_key=api_key,
                products=products,
                circuit_scope=circuit_scope,
            ),
            tool_layer=ProviderEvalToolLayer(products),
            composer=OpenAIAdvisorComposer(
                model=model,
                api_key=api_key,
                circuit_scope=circuit_scope,
            ),
            reliability_config=_provider_reliability_config(),
            provider_name="openai_advisor_first_pipeline",
            model_name=model,
        )
    audits: list[ProviderTurnAudit] = []
    for index, turn in enumerate(spec.turns, start=1):
        context = _provider_context_for_turn(spec, turn, index, state)
        output = await provider.generate(context)
        policy_issues = PolicyValidator().validate(output)
        before_fields = dict(state.fields)
        _apply_output_to_state(state, output)
        _remember_options(state, output)
        _apply_quote_phrase_tracking(state, output)
        state.conversation_progress = conversation_progress_memory(context, output)
        state.transcript.append({"role": "customer", "text": turn.message})
        state.transcript.append({"role": "assistant", "text": output.final_message})
        quote_snapshot = _last_quote_from_output(output)
        hard_failures = _hard_failures(turn, output, state, policy_issues)
        stale_quote = _stale_quote_detected(state.fields)
        product_changed = _product_changed(before_fields, state.fields)
        if product_changed and _active_quote_matches_previous(before_fields, state.fields):
            stale_quote = True
            hard_failures.append("product_changed_but_previous_quote_still_active")
        if product_changed and not _acknowledged_quote_reset(output.final_message):
            hard_failures.append("product_change_not_acknowledged_as_quote_reset")
        audits.append(
            ProviderTurnAudit(
                turn_index=index,
                customer_message=turn.message,
                attachments=turn.attachments,
                provider_used=str(output.trace_metadata.get("provider_used") or output.trace_metadata.get("provider")),
                raw_model_decision=output.trace_metadata.get("raw_model_decision"),
                raw_model_composer=output.trace_metadata.get("raw_model_composer"),
                advisor_decision=output.trace_metadata.get("advisor_brain") or {},
                tool_calls=output.trace_metadata.get("tool_results") or [],
                state_updates=[update.model_dump(mode="json") for update in output.field_updates],
                blocked_updates=output.trace_metadata.get("state_writer", {}).get("blocked") or [],
                final_message=output.final_message,
                quote_snapshot_id=quote_snapshot.get("snapshot_id") if quote_snapshot else None,
                quote_snapshot_hash=quote_snapshot.get("integrity_hash") if quote_snapshot else None,
                quote_safety=output.trace_metadata.get("quote_safety") or {},
                conversation_progress_guard=output.trace_metadata.get("conversation_progress_guard") or {},
                provider_reliability=(
                    output.trace_metadata.get("component_provider_reliability")
                    or output.trace_metadata.get("provider_reliability")
                    or {}
                ),
                previous_assistant_message=audits[-1].final_message if audits else "",
                quote_context_notes=list(output.trace_metadata.get("quote_context_notes") or []),
                robotic_phrase_score=_robotic_phrase_score(output.final_message),
                repeated_question_detected=_turn_repeated_question_detected(
                    [audit.final_message for audit in audits],
                    output.final_message,
                    turn.message,
                ),
                stale_quote_detected=stale_quote,
                human_review_notes=list(output.trace_metadata.get("human_review_notes") or []),
                model_emitted_internal_error_notes=list(
                    output.trace_metadata.get("model_emitted_internal_error_notes") or []
                ),
                pipeline_stage=state.stage,
                hard_validation_failures=hard_failures,
            )
        )
    failures = [failure for audit in audits for failure in audit.hard_validation_failures]
    repeated = any(audit.repeated_question_detected for audit in audits) or _repetition_detected([audit.final_message for audit in audits])
    stale = any(audit.stale_quote_detected for audit in audits)
    if repeated:
        failures.append("repeated_question_or_exact_response_detected")
    if stale:
        failures.append("stale_quote_detected")
    if state.quote_response_count and state.quote_phrase_count / state.quote_response_count > 0.2:
        failures.append("quote_active_phrase_over_20_percent")
    naturalidad = _provider_naturalidad_score(audits, failures)
    return ProviderCaseAudit(
        case_id=spec.case_id,
        title=spec.title,
        source=source,
        pass_fail="pass" if not failures else "fail",
        transcript=list(state.transcript),
        turns=audits,
        final_pipeline_stage=state.stage,
        naturalidad_score=naturalidad,
        repeated_question_detected=repeated,
        stale_quote_detected=stale,
        robotic_phrase_score=round(sum(a.robotic_phrase_score for a in audits) / len(audits), 2),
        failures=failures,
        human_review_notes=[note for audit in audits for note in audit.human_review_notes],
    )


def _provider_context_for_turn(spec: SimulationCaseSpec, turn: CustomerTurn, index: int, state: ProviderConversationState) -> TurnContext:
    context = _context_for_turn(spec, turn, index, state)  # type: ignore[arg-type]
    memory_metadata = dict(context.memory.metadata)
    memory_metadata["conversation_progress"] = dict(state.conversation_progress)
    return context.model_copy(
        update={
            "memory": context.memory.model_copy(update={"metadata": memory_metadata}),
            "tenant_config": tenant_config().model_copy(
                update={
                    "metadata": {
                        "canonical_catalog": [product.ref().model_dump(mode="json") for product in dinamo_products()],
                        "eval_mode": "provider_advisor_first",
                    }
                }
            ),
            "active_agent": context.active_agent.model_copy(
                update={
                    "instructions": (
                        "Actua como asesor comercial humano. Responde multiples necesidades "
                        "del mensaje antes de pedir datos. Usa herramientas y QuoteSnapshot; "
                        "si cambia el producto, reconoce que la cotizacion anterior ya no aplica."
                    ),
                    "tone": "natural, directo, asesor humano, sin formularios",
                    "enabled_action_ids": [
                        "catalog.lookup",
                        "quote.resolve",
                        "requirements.resolve",
                        "vision.document_analyze",
                        "handoff.request",
                    ],
                    "visible_contact_field_keys": VISIBLE_FIELDS,
                    "allowed_lifecycle_stage_ids": ALLOWED_STAGES,
                }
            )
            if context.active_agent
            else None,
        }
    )


def _advisor_brain_payload(context: TurnContext, products: list[Any]) -> dict[str, Any]:
    return {
        "message": context.inbound_text,
        "attachments": context.metadata.get("attachments") or [],
        "conversation_history": [message.model_dump(mode="json") for message in context.messages[-8:]],
        "memory": context.memory.model_dump(mode="json"),
        "lifecycle": context.lifecycle.model_dump(mode="json"),
        "tenant_config": context.tenant_config.model_dump(mode="json"),
        "canonical_catalog": [product.ref().model_dump(mode="json") for product in products],
        "visible_fields": VISIBLE_FIELDS,
        "allowed_stages": ALLOWED_STAGES,
        "available_tools": {
            "catalog.lookup": {"payload": {"query": "string OR canonical_product_ref"}},
            "quote.resolve": {
                "payload": {
                    "product": "CanonicalProductReference",
                    "plan_code": "cash|Sin Comprobantes",
                }
            },
            "requirements.resolve": {"payload": {"plan": "string|null"}},
            "handoff.create": {"payload": {"requested_person": "string|null"}},
            "faq.resolve": {"payload": {"topic": "ubicacion|buro|general"}},
        },
    }


def _advisor_brain_system_prompt() -> str:
    return advisor_brain_contract_system_rules()


def _parse_advisor_decision_lenient(raw_payload: dict[str, Any]) -> tuple[AdvisorBrainDecision, list[str]]:
    notes: list[str] = []
    payload = dict(raw_payload)
    changes: list[dict[str, Any]] = []
    for raw_change in payload.get("proposed_state_changes") or []:
        if not isinstance(raw_change, dict):
            notes.append("dropped_non_object_state_change")
            continue
        change = dict(raw_change)
        target = str(change.get("target") or "").strip()
        if target in {"product", "field", "contact"}:
            notes.append(f"coerced_state_target:{target}->contact_field")
            change["target"] = "contact_field"
            change.setdefault("key", "Producto" if target == "product" else None)
        elif target in {"stage", "pipeline", "lifecycle_stage"}:
            notes.append(f"coerced_state_target:{target}->lifecycle")
            change["target"] = "lifecycle"
        elif target not in {"contact_field", "lifecycle", "memory", "none"}:
            notes.append(f"coerced_unknown_state_target:{target or 'empty'}->none")
            change["target"] = "none"
        if not change.get("reason"):
            change["reason"] = "Model proposed this state change during provider evaluation."
            notes.append("filled_missing_state_change_reason")
        if not isinstance(change.get("evidence"), list) or not change.get("evidence"):
            change["evidence"] = [str(payload.get("understanding") or "provider evaluation")]
            notes.append("filled_missing_state_change_evidence")
        if not isinstance(change.get("metadata"), dict):
            change["metadata"] = {}
        changes.append(change)
    payload["proposed_state_changes"] = changes
    tools: list[dict[str, Any]] = []
    for raw_tool in payload.get("required_tools") or []:
        if not isinstance(raw_tool, dict):
            notes.append("dropped_non_object_tool_request")
            continue
        tool = dict(raw_tool)
        if not tool.get("name") and tool.get("tool_name"):
            tool["name"] = tool.pop("tool_name")
            notes.append("coerced_tool_name")
        tool.setdefault("payload", {})
        tool.setdefault("required", True)
        if not tool.get("reason"):
            tool["reason"] = "Model requested this tool during provider evaluation."
            notes.append("filled_missing_tool_reason")
        if not isinstance(tool.get("evidence"), list):
            tool["evidence"] = [tool["reason"]]
        if not isinstance(tool.get("metadata"), dict):
            tool["metadata"] = {}
        tools.append(tool)
    payload["required_tools"] = tools
    payload.setdefault("understanding", "Model did not provide explicit understanding.")
    payload.setdefault("customer_goal", None)
    payload.setdefault("conversation_goals", [])
    payload.setdefault("known_facts", {})
    payload.setdefault("missing_facts", [])
    payload.setdefault("next_best_action", "respond_with_context")
    payload.setdefault("response_plan", "Respond naturally using validated context and tools.")
    payload.setdefault("confidence", 0.5)
    payload.setdefault("needs_human", False)
    payload.setdefault("risk_flags", [])
    payload.setdefault("latest_customer_act", latest_customer_act(str(payload.get("understanding") or "")))
    payload.setdefault("new_information_detected", False)
    payload.setdefault("answered_slot", None)
    payload.setdefault("should_ask_question", False)
    payload.setdefault("question_slot", None)
    payload.setdefault("conversation_progress_action", "respond_to_latest_customer_act")
    payload.setdefault("metadata", {})
    try:
        return AdvisorBrainDecision.model_validate(payload), notes
    except ValidationError as exc:
        notes.append(f"fallback_after_validation_error:{exc.errors()[0].get('type') if exc.errors() else 'unknown'}")
        return (
            AdvisorBrainDecision(
                understanding=str(payload.get("understanding") or "Provider output could not be fully parsed."),
                customer_goal=str(payload.get("customer_goal") or "answer_question"),
                conversation_goals=[str(item) for item in payload.get("conversation_goals") or ["answer_question"]],
                known_facts=payload.get("known_facts") if isinstance(payload.get("known_facts"), dict) else {},
                missing_facts=[str(item) for item in payload.get("missing_facts") or []],
                next_best_action=str(payload.get("next_best_action") or "respond_with_context"),
                required_tools=[],
                proposed_state_changes=[],
                response_plan=str(payload.get("response_plan") or "Respond naturally using context."),
                confidence=0.4,
                needs_human=True,
                risk_flags=["advisor_decision_parse_repaired"],
                metadata={"parse_error": exc.errors()},
            ),
            notes,
        )


def _composer_system_prompt() -> str:
    return "\n".join(
        [
            "Eres Composer para un agente comercial. Redactas el mensaje final al "
            "cliente usando unicamente facts validados.",
            "",
            "Reglas criticas:",
            "",
            "1. No eres fuente de precios.",
            "2. No inventes ni recuerdes precios.",
            "3. No incluyas precio, enganche, mensualidad, plazo, contado o "
            "financiamiento si `quote_context.can_quote` no es true.",
            "4. Si `quote_context.can_quote` es true, usa el "
            "`quote_context.quote_snippet` exactamente para la parte de precio.",
            "5. No modifiques montos, plazos ni plan del quote_snippet.",
            "6. No uses precios que aparezcan en historial si no vienen dentro del "
            "quote_context.",
            "7. Si el guard o contexto indica blocked_reason, responde sin precio y "
            "pide/explica el siguiente paso.",
            "8. Se breve, natural y comercial.",
            "9. No repitas preguntas ya respondidas.",
            "10. No cierres con frases largas tipo "
            "\"si tienes mas preguntas no dudes...\" en cada turno.",
            "11. Usa conversation_progress_context para responder al ultimo acto del "
            "cliente.",
            "12. No preguntes slots incluidos en must_not_ask_slots.",
            "13. No repitas acciones incluidas en must_not_repeat_actions salvo que "
            "allowed_repeat sea true.",
            "14. Si el cliente dio un dato, confirmalo brevemente y avanza.",
            "15. Si el cliente dice ok, va o si, da un siguiente paso concreto.",
            "16. Si latest_customer_act es qualification_income o "
            "qualification_seniority, confirma el dato en una frase y no repitas "
            "documentos, cotizacion ni CTA largo.",
            "17. Si new_information_detected=true, no uses requirements.resolve como "
            "tema principal salvo que el cliente tambien haya pedido documentos.",
            "18. Si latest_customer_act es documents_question, responde documentos "
            "o explica especificamente que falta para definirlos; aqui si puedes "
            "repetirlos si el cliente los pidio.",
            "19. Si latest_customer_act es acknowledgement despues de cotizacion, "
            "da siguiente paso sin repetir la cotizacion completa.",
            "20. No respondas con frases genericas como \"avanzo con lo nuevo\" o "
            "\"sigo con ese contexto\".",
            "21. No inventes ni reportes errores internos de provider, circuit "
            "breaker, retry o timeout dentro de human_review_notes. Esas notas "
            "solo las agrega el harness si ocurren de verdad.",
            "",
            "Formato de salida:",
            "{",
            '  "final_message": string,',
            '  "human_review_notes": string[],',
            '  "used_quote_snapshot_id": string | null,',
            '  "used_quote_snapshot_hash": string | null',
            "}",
            "",
            "Ejemplos:",
            "",
            "Caso sin permiso de cotizar:",
            "quote_context.can_quote=false",
            'Cliente: "Cotizamela"',
            "Respuesta:",
            '"Ya tengo el modelo, pero necesito confirmar la cotizacion del sistema '
            'antes de darte precio para no pasarte un dato incorrecto."',
            "",
            "Caso con permiso:",
            "quote_context.can_quote=true",
            'quote_context.quote_snippet="De contado, la Adventure Elite 150 CC '
            'queda en $50,400."',
            'Cliente: "Cotizamela"',
            "Respuesta:",
            '"De contado, la Adventure Elite 150 CC queda en $50,400. Si te '
            'interesa, te puedo decir que documentos ocupas."',
            "",
            "Caso documentos:",
            'Cliente: "Que documentos necesito?"',
            "Respuesta:",
            '"De base ocupas INE y comprobante de domicilio. Segun el plan puede '
            'aplicar referencia o comprobante adicional."',
            "",
            "Caso humano:",
            'Cliente: "Quiero que alguien me confirme disponibilidad"',
            "Respuesta:",
            '"Claro, te paso con Francisco o con una persona del equipo para '
            'confirmarlo directo."',
        ]
    )


def _composer_output_json_schema() -> dict[str, Any]:
    return {
        "name": "advisor_composer_output",
        "strict": False,
        "schema": {
            "type": "object",
            "properties": {
                "final_message": {"type": "string"},
                "human_review_notes": {"type": "array", "items": {"type": "string"}},
                "used_quote_snapshot_id": {"type": ["string", "null"]},
                "used_quote_snapshot_hash": {"type": ["string", "null"]},
            },
            "required": [
                "final_message",
                "human_review_notes",
                "used_quote_snapshot_id",
                "used_quote_snapshot_hash",
            ],
            "additionalProperties": False,
        },
    }


def _trusted_composer_human_review_notes(
    raw_payload: dict[str, Any],
    *,
    model_response_succeeded: bool,
) -> list[str]:
    notes = [str(note) for note in raw_payload.get("human_review_notes") or []]
    if not model_response_succeeded:
        return notes
    return [note for note in notes if not _internal_provider_error_note(note)]


def _model_emitted_internal_error_notes(
    raw_payload: dict[str, Any],
    *,
    model_response_succeeded: bool,
) -> list[str]:
    if not model_response_succeeded:
        return []
    return [
        str(note)
        for note in raw_payload.get("human_review_notes") or []
        if _internal_provider_error_note(str(note))
    ]


def _internal_provider_error_note(note: str) -> bool:
    folded = note.casefold()
    return (
        "provider" in folded
        and any(
            token in folded
            for token in (
                "error",
                "circuit",
                "retry",
                "timeout",
                "ratelimit",
                "rate_limit",
                "429",
            )
        )
    )


def _normalize_tool_request(context: TurnContext, tool: AdvisorBrainToolRequest) -> AdvisorBrainToolRequest:
    payload = dict(tool.payload)
    if tool.name == "quote.resolve":
        if not payload.get("plan_code"):
            payload["plan_code"] = context.memory.salient_facts.get("Plan_Credito") or "cash"
    if tool.name == "catalog.lookup" and not payload:
        payload["query"] = context.inbound_text
    return tool.model_copy(update={"payload": payload})


def _quote_from_tool_results(results: list[ToolExecutionResult]) -> dict[str, Any] | None:
    for result in results:
        snapshot = result.data.get("quote_snapshot")
        if isinstance(snapshot, dict):
            return snapshot
    return None


def _coerce_product_ref(value: Any, aliases: AliasMap) -> CanonicalProductReference | None:
    if isinstance(value, CanonicalProductReference):
        return value
    if isinstance(value, dict):
        try:
            return CanonicalProductReference.model_validate(value)
        except ValueError:
            for key in ("display_name", "sku", "product_id", "query"):
                if value.get(key):
                    resolved = aliases.resolve(str(value[key]))
                    if resolved:
                        return resolved
    if isinstance(value, str) and value.strip():
        resolved = aliases.resolve(value)
        if resolved:
            return resolved
        folded = fold(value)
        if "advent" in folded:
            return aliases.resolve("adventure")
        if "r4" in folded or folded in {"r", "erre cuatro"}:
            return aliases.resolve("r4")
        if "u5" in folded or "u cinco" in folded:
            return aliases.resolve("u5")
        if "barata" in folded or "trabajo" in folded:
            return aliases.resolve("moto de trabajo")
    return None


def _provider_reliability_config() -> ProviderReliabilityConfig:
    settings = get_settings()
    return ProviderReliabilityConfig(
        max_retries=settings.agent_runtime_v2_model_max_retries,
        timeout_s=settings.agent_runtime_v2_model_timeout_s,
        base_delay_ms=settings.agent_runtime_v2_model_retry_base_delay_ms,
        max_delay_ms=settings.agent_runtime_v2_model_retry_max_delay_ms,
        jitter_ms=settings.agent_runtime_v2_model_retry_jitter_ms,
        circuit_failure_threshold=settings.agent_runtime_v2_provider_circuit_failure_threshold,
        circuit_cooldown_s=settings.agent_runtime_v2_provider_circuit_cooldown_s,
        retry_output_parse_failures=True,
    )


def _fallback_reliability_snapshot(exc: BaseException) -> dict[str, Any]:
    preserved = getattr(exc, "provider_reliability_snapshot", None)
    if isinstance(preserved, dict):
        return preserved
    kind = classify_provider_error(exc)
    last = getattr(exc, "last_error", None)
    if isinstance(exc, ProviderRetryExhaustedError) and last is not None:
        kind = classify_provider_error(last)
    return {
        "provider_error_rate": 1.0,
        "provider_429_count": 1 if kind == "429" else 0,
        "provider_timeout_count": 1 if kind == "timeout" else 0,
        "provider_5xx_count": 1 if kind == "5xx" else 0,
        "provider_retry_count": 0,
        "provider_retry_exhausted_count": 1 if isinstance(exc, ProviderRetryExhaustedError) else 0,
        "provider_circuit_breaker_open_count": 1 if kind == "circuit_open" else 0,
        "provider_fallback_response_count": 1,
        "provider_latency_p50": 0,
        "provider_latency_p95": 0,
        "provider_latency_p99": 0,
        "provider_call_count": 1,
        "provider_error_count": 1,
        "circuit_state": "unknown",
        "last_error_kind": kind,
    }


def _deterministic_composer_fallback_message(
    context: TurnContext,
    quote_context: Any,
    tool_results: list[ToolExecutionResult],
) -> str:
    if quote_context.can_quote and quote_context.quote_snippet:
        return f"Perfecto, uso la cotizacion validada del sistema. {quote_context.quote_snippet}"
    requirements = []
    for result in tool_results:
        raw = result.data.get("requirements")
        if isinstance(raw, list):
            requirements = [str(item) for item in raw if str(item).strip()]
            break
    if requirements:
        return f"Para este paso ocupas: {', '.join(requirements)}. Los revisamos antes de avanzar."
    if any(
        result.tool_name in {"handoff.request", "handoff.create"}
        and result.status == "succeeded"
        and bool(result.data.get("handoff_required") or result.data.get("handoff_created"))
        for result in tool_results
    ):
        return "Listo, ya quedo solicitado el apoyo de una persona del equipo."
    if "humano" in fold(context.inbound_text) or "asesor" in fold(context.inbound_text):
        return "Necesito que una persona del equipo revise esto para responderte con certeza."
    return "Necesito que una persona del equipo revise esto para responderte con certeza."


def _provider_payload(cases: list[ProviderCaseAudit], local_payload: dict[str, Any]) -> dict[str, Any]:
    total_turns = sum(len(case.turns) for case in cases)
    repeated_turns = sum(1 for case in cases for turn in case.turns if turn.repeated_question_detected)
    stale_turns = sum(1 for case in cases for turn in case.turns if turn.stale_quote_detected)
    all_turns = [turn for case in cases for turn in case.turns]
    progress_turns = [turn for turn in all_turns if turn.conversation_progress_guard]
    progress_sanitized = sum(
        1 for turn in progress_turns if str(turn.conversation_progress_guard.get("action") or "") == "sanitized"
    )
    exact_response_repeats = sum(1 for turn in all_turns if _final_exact_repeat(turn))
    repeated_slot_questions = sum(
        1 for turn in progress_turns if "same_slot_question_repeated" in _progress_failures(turn)
    )
    repeated_quotes_without_request = sum(
        1 for turn in progress_turns if "quote_repeated_without_user_asking" in _progress_failures(turn)
    )
    repeated_requirements_without_request = sum(
        1 for turn in progress_turns if "requirements_repeated_without_user_asking" in _progress_failures(turn)
    )
    generic_sanitizer_fallbacks = sum(
        1 for turn in all_turns if _generic_sanitizer_fallback_detected(turn.final_message)
    )
    answer_relevant = sum(1 for turn in all_turns if _answer_relevance_ok(turn))
    document_request_turns = [turn for turn in all_turns if latest_customer_act(turn.customer_message) == "documents_question"]
    document_requests_answered = sum(1 for turn in document_request_turns if _documents_answered(turn.final_message))
    quoted_without_canonical_product = sum(
        1
        for turn in all_turns
        if "quoted_without_canonical_product" in _turn_quote_failures(turn)
        or "quoted_without_canonical_product" in turn.hard_validation_failures
    )
    price_without_snapshot = sum(
        1
        for turn in all_turns
        if "visible_price_without_quote_permission" in _turn_quote_failures(turn)
    )
    amount_mismatch = sum(
        1 for turn in all_turns if "quote_amount_not_in_snapshot" in _turn_quote_failures(turn)
    )
    guard_blocks = sum(
        1 for turn in all_turns if str(turn.quote_safety.get("action") or "") == "rewritten"
    )
    sanitized_messages = sum(
        1
        for turn in all_turns
        if str(turn.quote_safety.get("action") or "") == "rewritten"
        or any("removed_price" in note for note in turn.quote_context_notes)
    )
    quote_turns = [
        turn for case in cases for turn in case.turns if turn.quote_snapshot_id or _mentions_money(turn.final_message)
    ]
    quote_phrase_hits = sum(
        1 for turn in quote_turns if "te lo dejo como cotizacion activa" in fold(turn.final_message)
    )
    avg_naturalidad = round(sum(case.naturalidad_score for case in cases) / len(cases), 2)
    quote_phrase_rate_ok = quote_phrase_hits / len(quote_turns) <= 0.2 if quote_turns else True
    repeated_question_rate = repeated_turns / total_turns if total_turns else 0
    progress_guard_block_rate = _progress_guard_block_rate(progress_sanitized, total_turns)
    provider_metrics = _aggregate_provider_reliability(all_turns)
    definition_of_done_pass = (
        all(case.pass_fail == "pass" for case in cases)
        and avg_naturalidad >= 4.2
        and repeated_question_rate <= 0.02
        and stale_turns == 0
        and exact_response_repeats == 0
        and quoted_without_canonical_product == 0
        and price_without_snapshot == 0
        and amount_mismatch == 0
        and quote_phrase_rate_ok
        and _progress_guard_sanitization_within_gate(progress_sanitized, total_turns)
        and repeated_requirements_without_request == 0
        and generic_sanitizer_fallbacks == 0
    )
    payload = {
        "summary": {
            "provider_used": "openai",
            "model": get_settings().agent_runtime_v2_model,
            **provider_metrics,
            "cases_total": len(cases),
            "cases_passed": sum(1 for case in cases if case.pass_fail == "pass"),
            "cases_failed": sum(1 for case in cases if case.pass_fail == "fail"),
            "turns_total": total_turns,
            "naturalidad_avg": avg_naturalidad,
            "repeated_question_rate": round(repeated_question_rate, 4),
            "exact_response_repeat_rate": round(exact_response_repeats / total_turns if total_turns else 0, 4),
            "repeated_slot_question_rate": round(repeated_slot_questions / total_turns if total_turns else 0, 4),
            "repeated_quote_without_request_rate": round(
                repeated_quotes_without_request / total_turns if total_turns else 0,
                4,
            ),
            "repeated_requirements_without_request_rate": round(
                repeated_requirements_without_request / total_turns if total_turns else 0,
                4,
            ),
            "stale_quote_rate": round(stale_turns / total_turns if total_turns else 0, 4),
            "quoted_without_canonical_product_rate": round(
                quoted_without_canonical_product / total_turns if total_turns else 0,
                4,
            ),
            "price_without_snapshot_rate": round(
                price_without_snapshot / total_turns if total_turns else 0,
                4,
            ),
            "price_amount_mismatch_rate": round(
                amount_mismatch / total_turns if total_turns else 0,
                4,
            ),
            "quote_guard_blocks_total": guard_blocks,
            "progress_guard_blocks_total": progress_sanitized,
            "progress_guard_block_rate": progress_guard_block_rate,
            "sanitized_messages_count": sanitized_messages,
            "progress_guard_sanitized_messages_count": progress_sanitized,
            "generic_sanitizer_fallback_rate": round(
                generic_sanitizer_fallbacks / total_turns if total_turns else 0,
                4,
            ),
            "answer_relevance_rate": round(answer_relevant / total_turns if total_turns else 1, 4),
            "documents_request_answered_rate": round(
                document_requests_answered / len(document_request_turns) if document_request_turns else 1,
                4,
            ),
            "conversation_progress_rate": round(
                (total_turns - repeated_turns) / total_turns if total_turns else 1,
                4,
            ),
            "quote_active_phrase_rate": round(quote_phrase_hits / len(quote_turns) if quote_turns else 0, 4),
            "side_effects": {"whatsapp": 0, "outbox": 0, "database_writes": 0},
            "definition_of_done_pass": definition_of_done_pass,
        },
        "cases": [_case_to_dict(case) for case in cases],
        "local_baseline_summary": local_payload.get("summary", {}),
        "comparison": _comparison_summary(cases, local_payload),
    }
    return payload


def _progress_guard_block_rate(progress_sanitized: int, total_turns: int) -> float:
    return round(progress_sanitized / total_turns if total_turns else 0, 4)


def _progress_guard_sanitization_within_gate(
    progress_sanitized: int,
    total_turns: int,
) -> bool:
    return _progress_guard_block_rate(progress_sanitized, total_turns) <= 0.05


def _aggregate_provider_reliability(turns: list[ProviderTurnAudit]) -> dict[str, Any]:
    snapshots: list[dict[str, Any]] = []
    for turn in turns:
        reliability = turn.provider_reliability
        if not isinstance(reliability, dict):
            continue
        nested = [
            value for value in reliability.values() if isinstance(value, dict)
        ]
        if nested:
            snapshots.extend(nested)
        else:
            snapshots.append(reliability)
    latencies: list[int] = []
    calls = 0
    errors = 0
    metrics = {
        "provider_429_count": 0,
        "provider_timeout_count": 0,
        "provider_5xx_count": 0,
        "provider_retry_count": 0,
        "provider_retry_exhausted_count": 0,
        "provider_circuit_breaker_open_count": 0,
        "provider_fallback_response_count": 0,
    }
    for snapshot in snapshots:
        calls += int(snapshot.get("provider_call_count") or 0)
        errors += int(snapshot.get("provider_error_count") or 0)
        for key in metrics:
            metrics[key] += int(snapshot.get(key) or 0)
        for key in ("provider_latency_p50", "provider_latency_p95", "provider_latency_p99"):
            value = int(snapshot.get(key) or 0)
            if value:
                latencies.append(value)
    latencies.sort()
    return {
        "provider_error_rate": round(errors / calls if calls else 0, 4),
        **metrics,
        "provider_latency_p50": _percentile(latencies, 50),
        "provider_latency_p95": _percentile(latencies, 95),
        "provider_latency_p99": _percentile(latencies, 99),
    }


def _turn_quote_failures(turn: ProviderTurnAudit) -> list[str]:
    failures = turn.quote_safety.get("failures")
    return [str(item) for item in failures] if isinstance(failures, list) else []


def _percentile(values: list[int], percentile: int) -> int:
    if not values:
        return 0
    if len(values) == 1:
        return values[0]
    index = round((percentile / 100) * (len(values) - 1))
    return values[min(max(index, 0), len(values) - 1)]


def _progress_failures(turn: ProviderTurnAudit) -> list[str]:
    failures = turn.conversation_progress_guard.get("failures")
    return [str(item) for item in failures] if isinstance(failures, list) else []


def _final_exact_repeat(turn: ProviderTurnAudit) -> bool:
    return bool(turn.previous_assistant_message and fold(turn.previous_assistant_message) == fold(turn.final_message))


def _generic_sanitizer_fallback_detected(message: str) -> bool:
    folded = fold(message)
    return any(
        phrase in folded
        for phrase in (
            "avanzo con lo nuevo",
            "evito repetir",
            "sigo con ese contexto",
        )
    )


def _answer_relevance_ok(turn: ProviderTurnAudit) -> bool:
    act = latest_customer_act(turn.customer_message)
    message = turn.final_message
    folded = fold(message)
    if act == "documents_question":
        return _documents_answered(message)
    if act == "quote_request":
        return visible_quote_signal(message) or _quote_block_explained(message)
    if act == "handoff_request":
        return any(word in folded for word in ("humano", "asesor", "francisco", "fransisko", "persona"))
    if _product_change_signal(turn.customer_message):
        return any(word in folded for word in ("cambio", "nuevo modelo", "actualizo", "r4", "u5", "adventure"))
    return True


def _documents_answered(message: str) -> bool:
    folded = fold(message)
    return (
        "ine" in folded
        and ("comprobante" in folded or "domicilio" in folded)
    ) or (
        ("document" in folded or "requisito" in folded or "papel" in folded)
        and ("confirm" in folded or "plan" in folded or "falta" in folded)
    )


def _quote_block_explained(message: str) -> bool:
    folded = fold(message)
    return "cotizacion" in folded and (
        "confirm" in folded or "sistema" in folded or "modelo" in folded or "plan" in folded
    )


def _product_change_signal(message: str) -> bool:
    folded = fold(message)
    return any(word in folded for word in ("otra", "cambio", "mejor", "segunda", "r4", "u5", "adventure"))


def _explicit_documents_request(message: str) -> bool:
    folded = fold(message)
    return any(word in folded for word in ("document", "requisito", "papel", "papeles"))


def _case_to_dict(case: ProviderCaseAudit) -> dict[str, Any]:
    return {
        "case_id": case.case_id,
        "title": case.title,
        "source": case.source,
        "pass_fail": case.pass_fail,
        "final_pipeline_stage": case.final_pipeline_stage,
        "naturalidad_score": case.naturalidad_score,
        "repeated_question_detected": case.repeated_question_detected,
        "stale_quote_detected": case.stale_quote_detected,
        "robotic_phrase_score": case.robotic_phrase_score,
        "failures": case.failures,
        "human_review_notes": case.human_review_notes,
        "transcript": case.transcript,
        "turns": [turn.__dict__ for turn in case.turns],
    }


def _write_provider_reports(payload: dict[str, Any]) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    PROVIDER_REPORT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    PROVIDER_REPORT_MD.write_text(_provider_markdown(payload), encoding="utf-8")
    COMPARISON_MD.write_text(_comparison_markdown(payload), encoding="utf-8")
    ROBOTIC_AUDIT_MD.write_text(_robotic_audit_markdown(payload), encoding="utf-8")
    STALE_QUOTE_AUDIT_MD.write_text(_stale_quote_markdown(payload), encoding="utf-8")
    repetition_payload = _repetition_audit_payload(payload)
    REPETITION_AUDIT_JSON.write_text(json.dumps(repetition_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    REPETITION_AUDIT_MD.write_text(_repetition_audit_markdown(repetition_payload), encoding="utf-8")


def _provider_markdown(payload: dict[str, Any]) -> str:
    rows = [
        f"| {case['case_id']} | {case['source']} | {case['pass_fail']} | {case['final_pipeline_stage']} | "
        f"{case['naturalidad_score']} | {case['repeated_question_detected']} | {case['stale_quote_detected']} | "
        f"{', '.join(case['failures']) or 'ok'} |"
        for case in payload["cases"]
    ]
    examples = []
    for case in payload["cases"][:12]:
        if case["transcript"]:
            examples.append(f"- `{case['case_id']}`: {case['transcript'][-1]['text']}")
    return "\n".join(
        [
            "# Provider Advisor-first Evaluation",
            "",
            "## Executive Summary",
            "",
            f"- provider_used: `{payload['summary']['provider_used']}`",
            f"- model: `{payload['summary']['model']}`",
            f"- provider_error_rate: `{payload['summary']['provider_error_rate']}`",
            f"- provider_429_count: `{payload['summary']['provider_429_count']}`",
            f"- provider_timeout_count: `{payload['summary']['provider_timeout_count']}`",
            f"- provider_5xx_count: `{payload['summary']['provider_5xx_count']}`",
            f"- provider_retry_count: `{payload['summary']['provider_retry_count']}`",
            "- provider_retry_exhausted_count: "
            f"`{payload['summary']['provider_retry_exhausted_count']}`",
            "- provider_circuit_breaker_open_count: "
            f"`{payload['summary']['provider_circuit_breaker_open_count']}`",
            "- provider_fallback_response_count: "
            f"`{payload['summary']['provider_fallback_response_count']}`",
            f"- provider_latency_p50: `{payload['summary']['provider_latency_p50']}`",
            f"- provider_latency_p95: `{payload['summary']['provider_latency_p95']}`",
            f"- provider_latency_p99: `{payload['summary']['provider_latency_p99']}`",
            f"- cases_passed: `{payload['summary']['cases_passed']}/{payload['summary']['cases_total']}`",
            f"- naturalidad_avg: `{payload['summary']['naturalidad_avg']}`",
            f"- repeated_question_rate: `{payload['summary']['repeated_question_rate']}`",
            f"- exact_response_repeat_rate: `{payload['summary']['exact_response_repeat_rate']}`",
            f"- repeated_slot_question_rate: `{payload['summary']['repeated_slot_question_rate']}`",
            "- repeated_quote_without_request_rate: "
            f"`{payload['summary']['repeated_quote_without_request_rate']}`",
            "- repeated_requirements_without_request_rate: "
            f"`{payload['summary']['repeated_requirements_without_request_rate']}`",
            f"- progress_guard_blocks_total: `{payload['summary']['progress_guard_blocks_total']}`",
            f"- progress_guard_block_rate: `{payload['summary']['progress_guard_block_rate']}`",
            "- progress_guard_sanitized_messages_count: "
            f"`{payload['summary']['progress_guard_sanitized_messages_count']}`",
            "- generic_sanitizer_fallback_rate: "
            f"`{payload['summary']['generic_sanitizer_fallback_rate']}`",
            f"- answer_relevance_rate: `{payload['summary']['answer_relevance_rate']}`",
            "- documents_request_answered_rate: "
            f"`{payload['summary']['documents_request_answered_rate']}`",
            f"- conversation_progress_rate: `{payload['summary']['conversation_progress_rate']}`",
            f"- stale_quote_rate: `{payload['summary']['stale_quote_rate']}`",
            "- quoted_without_canonical_product_rate: "
            f"`{payload['summary']['quoted_without_canonical_product_rate']}`",
            f"- price_without_snapshot_rate: `{payload['summary']['price_without_snapshot_rate']}`",
            f"- price_amount_mismatch_rate: `{payload['summary']['price_amount_mismatch_rate']}`",
            f"- quote_guard_blocks_total: `{payload['summary']['quote_guard_blocks_total']}`",
            f"- sanitized_messages_count: `{payload['summary']['sanitized_messages_count']}`",
            f"- quote_active_phrase_rate: `{payload['summary']['quote_active_phrase_rate']}`",
            f"- definition_of_done_pass: `{payload['summary']['definition_of_done_pass']}`",
            "- side_effects: `whatsapp=0`, `outbox=0`, `database_writes=0`",
            "",
            "## Case Matrix",
            "",
            "| case | source | pass/fail | final_stage | naturalidad | repeated_question | stale_quote | failures |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
            *rows,
            "",
            "## Response Examples",
            "",
            *(examples or ["- none"]),
        ]
    )


def _repetition_audit_payload(payload: dict[str, Any]) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for case in payload["cases"]:
        for turn in case["turns"]:
            progress = turn.get("conversation_progress_guard") or {}
            failures = [str(item) for item in progress.get("failures") or []]
            old_repeat = bool(turn.get("repeated_question_detected"))
            if not failures and not old_repeat:
                continue
            category = _repetition_category(turn, failures)
            metrics = progress.get("metrics") if isinstance(progress.get("metrics"), dict) else {}
            advisor = turn.get("advisor_decision") if isinstance(turn.get("advisor_decision"), dict) else {}
            entries.append(
                {
                    "category": category,
                    "case_id": case["case_id"],
                    "turn_index": turn["turn_index"],
                    "customer_message": turn["customer_message"],
                    "previous_assistant_message": turn.get("previous_assistant_message") or "",
                    "current_assistant_message": turn["final_message"],
                    "similarity": metrics.get("similarity_to_last_assistant", 0),
                    "advisor_next_best_action": advisor.get("next_best_action"),
                    "latest_customer_act": advisor.get("latest_customer_act"),
                    "known_facts": advisor.get("known_facts") or {},
                    "quote_guard_result": turn.get("quote_safety") or {},
                    "suspected_root_cause": _suspected_repetition_root_cause(category, turn, failures),
                }
            )
    return {
        "summary": {
            "entries_total": len(entries),
            "categories": {
                category: sum(1 for entry in entries if entry["category"] == category)
                for category in (
                    "exact_response_repeat",
                    "same_slot_question_repeated",
                    "quote_repeated_without_user_asking",
                    "requirements_repeated_without_user_asking",
                    "guard_fallback_repeated",
                    "generic_cta_repeated",
                    "advisor_next_action_stuck",
                    "composer_ignored_new_user_signal",
                )
            },
        },
        "entries": entries,
    }


def _repetition_category(turn: dict[str, Any], failures: list[str]) -> str:
    if "exact_response_repeat" in failures or (
        turn.get("previous_assistant_message") and fold(turn.get("previous_assistant_message")) == fold(turn.get("final_message"))
    ):
        return "exact_response_repeat"
    for category in (
        "same_slot_question_repeated",
        "quote_repeated_without_user_asking",
        "requirements_repeated_without_user_asking",
        "guard_fallback_repeated",
        "generic_cta_repeated",
    ):
        if category in failures:
            return category
    advisor = turn.get("advisor_decision") if isinstance(turn.get("advisor_decision"), dict) else {}
    if advisor.get("next_best_action") and advisor.get("conversation_progress_action") == "repeat_previous_action":
        return "advisor_next_action_stuck"
    return "composer_ignored_new_user_signal"


def _suspected_repetition_root_cause(category: str, turn: dict[str, Any], failures: list[str]) -> str:
    if category == "same_slot_question_repeated":
        metrics = turn.get("conversation_progress_guard", {}).get("metrics") or {}
        return f"Composer asked an already answered slot: {metrics.get('repeated_slot') or 'unknown'}."
    if category == "quote_repeated_without_user_asking":
        return "Composer repeated the active quote even though the customer did not ask for price again."
    if category == "requirements_repeated_without_user_asking":
        return "Composer repeated document requirements after an acknowledgement or unrelated signal."
    if category == "guard_fallback_repeated":
        return "Safety fallback was repeated without advancing the clarification."
    if category == "generic_cta_repeated":
        return "Composer reused a generic CTA from the previous answer."
    if category == "exact_response_repeat":
        return "Final assistant message matched the previous assistant message exactly."
    if failures:
        return f"Progress guard failures: {', '.join(failures)}."
    return "Advisor or Composer did not incorporate the latest customer signal."


def _repetition_audit_markdown(payload: dict[str, Any]) -> str:
    lines = ["# Provider Repetition Audit", ""]
    lines.append(f"- entries_total: `{payload['summary']['entries_total']}`")
    for category, count in payload["summary"]["categories"].items():
        lines.append(f"- {category}: `{count}`")
    lines.append("")
    for entry in payload["entries"]:
        lines.append(f"## {entry['case_id']} turn {entry['turn_index']} - {entry['category']}")
        lines.append(f"- customer_message: `{entry['customer_message']}`")
        lines.append(f"- similarity: `{entry['similarity']}`")
        lines.append(f"- advisor_next_best_action: `{entry['advisor_next_best_action']}`")
        lines.append(f"- latest_customer_act: `{entry['latest_customer_act']}`")
        lines.append(f"- suspected_root_cause: {entry['suspected_root_cause']}")
        lines.append(f"- previous: `{entry['previous_assistant_message']}`")
        lines.append(f"- current: `{entry['current_assistant_message']}`")
        lines.append("")
    if not payload["entries"]:
        lines.append("No repetition failures detected.")
    return "\n".join(lines)


def _comparison_markdown(payload: dict[str, Any]) -> str:
    comparison = payload["comparison"]
    return "\n".join(
        [
            "# Provider vs Local Comparison",
            "",
            f"- local_cases_passed: `{comparison['local_cases_passed']}`",
            f"- provider_base_cases_passed: `{comparison['provider_base_cases_passed']}`",
            f"- provider_adversarial_cases_passed: `{comparison['provider_adversarial_cases_passed']}`",
            f"- provider_naturalidad_avg: `{payload['summary']['naturalidad_avg']}`",
            f"- local_naturalidad_avg: `{payload['local_baseline_summary'].get('average_naturalidad')}`",
            "",
            "## Observations",
            "",
            *[f"- {item}" for item in comparison["observations"]],
        ]
    )


def _robotic_audit_markdown(payload: dict[str, Any]) -> str:
    lines = ["# Robotic Phrase Audit", ""]
    lines.append(f"- quote_active_phrase_rate: `{payload['summary']['quote_active_phrase_rate']}`")
    lines.append("")
    for case in payload["cases"]:
        hits = [
            turn for turn in case["turns"]
            if turn["robotic_phrase_score"] > 0
        ]
        if hits:
            lines.append(f"## {case['case_id']} - {case['title']}")
            for turn in hits:
                lines.append(f"- turn {turn['turn_index']}: score={turn['robotic_phrase_score']} `{turn['final_message']}`")
            lines.append("")
    if len(lines) == 3:
        lines.append("No robotic phrase hits detected.")
    return "\n".join(lines)


def _stale_quote_markdown(payload: dict[str, Any]) -> str:
    lines = ["# Stale Quote Audit", ""]
    lines.append(f"- stale_quote_rate: `{payload['summary']['stale_quote_rate']}`")
    lines.append("")
    for case in payload["cases"]:
        hits = [turn for turn in case["turns"] if turn["stale_quote_detected"]]
        if hits:
            lines.append(f"## {case['case_id']} - {case['title']}")
            for turn in hits:
                lines.append(f"- turn {turn['turn_index']}: `{turn['final_message']}`")
            lines.append("")
    if len(lines) == 3:
        lines.append("No stale quotes detected.")
    return "\n".join(lines)


def _comparison_summary(cases: list[ProviderCaseAudit], local_payload: dict[str, Any]) -> dict[str, Any]:
    base = [case for case in cases if case.source == "base"]
    adversarial = [case for case in cases if case.source == "adversarial"]
    observations = [
        "Local simulation is deterministic and only covers the original 10 cases.",
        "Provider run uses GPT for AdvisorBrain and Composer, while tools and StateWriter stay deterministic.",
    ]
    provider_failures = [case for case in cases if case.failures]
    if provider_failures:
        observations.append(f"Provider produced {len(provider_failures)} cases with validation failures; inspect provider_advisor_first_eval.json.")
    else:
        observations.append("Provider passed all hard validations in this dry-run harness.")
    return {
        "local_cases_passed": local_payload.get("summary", {}).get("cases_passed"),
        "provider_base_cases_passed": sum(1 for case in base if case.pass_fail == "pass"),
        "provider_adversarial_cases_passed": sum(1 for case in adversarial if case.pass_fail == "pass"),
        "observations": observations,
    }


def _apply_quote_phrase_tracking(state: ProviderConversationState, output: TurnOutput) -> None:
    if _last_quote_from_output(output) or _mentions_money(output.final_message):
        state.quote_response_count += 1
        if "te lo dejo como cotizacion activa" in fold(output.final_message):
            state.quote_phrase_count += 1


def _robotic_phrase_score(message: str) -> int:
    folded = fold(message)
    score = 0
    phrases = [
        "te lo dejo como cotizacion activa",
        "en que te puedo ayudar",
        "para poder ayudarte necesito",
        "por favor proporciona",
        "como formulario",
    ]
    for phrase in phrases:
        if phrase in folded:
            score += 1
    if len(message.split()) <= 4:
        score += 1
    return score


def _turn_repeated_question_detected(previous_messages: list[str], current: str, customer_message: str) -> bool:
    folded = fold(current)
    customer_act = latest_customer_act(customer_message)
    quote_repeat_allowed = (
        customer_act in {"quote_request", "repeat_quote_request"}
        and (visible_quote_signal(current) or _quote_block_explained(current))
    )
    documents_repeat_allowed = (
        customer_act == "documents_question"
        and _explicit_documents_request(customer_message)
        and _documents_answered(current)
    )
    if (
        not quote_repeat_allowed
        and not documents_repeat_allowed
        and folded in {fold(message) for message in previous_messages}
    ):
        return True
    if _asks_seniority(folded) and any(_asks_seniority(fold(message)) for message in previous_messages):
        return True
    if _asks_income(folded) and any(_asks_income(fold(message)) for message in previous_messages):
        return True
    return False


def _asks_seniority(folded: str) -> bool:
    return (
        "cuanto tiempo llevas trabajando" in folded
        or "cual es tu antiguedad" in folded
        or "que antiguedad laboral" in folded
    )


def _asks_income(folded: str) -> bool:
    return "como recibes tus ingresos" in folded or "tipo de ingreso" in folded


def _stale_quote_detected(fields: dict[str, Any]) -> bool:
    product = fields.get("Producto")
    quote = fields.get("Ultima_Cotizacion")
    if not isinstance(product, dict) or not isinstance(quote, dict):
        return False
    quote_product = quote.get("product") if isinstance(quote.get("product"), dict) else {}
    return bool(quote_product.get("product_id") and product.get("product_id") and quote_product.get("product_id") != product.get("product_id"))


def _product_changed(before: dict[str, Any], after: dict[str, Any]) -> bool:
    before_product = before.get("Producto") if isinstance(before.get("Producto"), dict) else {}
    after_product = after.get("Producto") if isinstance(after.get("Producto"), dict) else {}
    return bool(before_product.get("product_id") and after_product.get("product_id") and before_product.get("product_id") != after_product.get("product_id"))


def _active_quote_matches_previous(before: dict[str, Any], after: dict[str, Any]) -> bool:
    before_product = before.get("Producto") if isinstance(before.get("Producto"), dict) else {}
    quote = after.get("Ultima_Cotizacion") if isinstance(after.get("Ultima_Cotizacion"), dict) else {}
    quote_product = quote.get("product") if isinstance(quote.get("product"), dict) else {}
    return bool(before_product.get("product_id") and quote_product.get("product_id") == before_product.get("product_id"))


def _acknowledged_quote_reset(message: str) -> bool:
    folded = fold(message)
    return any(
        phrase in folded
        for phrase in (
            "cotizacion anterior",
            "ya no aplica",
            "cambia",
            "actualizo",
            "nuevo modelo",
            "otra cotizacion",
            "recalcular",
        )
    )


def _provider_naturalidad_score(audits: list[ProviderTurnAudit], failures: list[str]) -> float:
    score = 5.0
    if any(audit.robotic_phrase_score for audit in audits):
        score -= 0.4
    if any(audit.repeated_question_detected for audit in audits):
        score -= 0.7
    if any(len(audit.final_message.split()) < 5 for audit in audits):
        score -= 0.4
    if any(audit.final_message.count("?") > 1 for audit in audits):
        score -= 0.3
    if failures:
        score -= min(1.0, len(set(failures)) * 0.2)
    return round(max(1.0, score), 2)


def _mentions_money(message: str) -> bool:
    folded = fold(message)
    return "$" in message or "enganche" in folded or "pagos" in folded or "precio" in folded


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--case-id",
        action="append",
        dest="case_ids",
        help="Run only the selected provider eval case id. Repeat for multiple cases.",
    )
    args = parser.parse_args()
    payload = asyncio.run(run_provider_eval(set(args.case_ids or []) or None))
    print(json.dumps(payload["summary"], ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
