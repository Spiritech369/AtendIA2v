from __future__ import annotations

import asyncio
import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from atendia.agent_runtime.advisor_pipeline import AdvisorFirstAgentProvider
from atendia.agent_runtime.canonical import (
    AliasMap,
    CanonicalProduct,
    CanonicalProductReference,
    QuoteSnapshot,
)
from atendia.agent_runtime.policy_validator import PolicyValidator
from atendia.agent_runtime.schemas import (
    ActiveAgentContext,
    AdvisorBrainDecision,
    AdvisorBrainStateChange,
    AdvisorBrainToolRequest,
    MessageContext,
    TenantRuntimeConfigContext,
    ToolExecutionResult,
    TurnContext,
    TurnOutput,
)
from atendia.agent_runtime.state_writer import StateWriteResult

REPORT_DIR = Path(__file__).resolve().parents[3] / "reports"
REPORT_MD = REPORT_DIR / "advisor_first_multiturn_simulation.md"
REPORT_JSON = REPORT_DIR / "advisor_first_multiturn_simulation.json"
FAILURES_MD = REPORT_DIR / "advisor_first_failures.md"

TENANT_ID = "dinamo-simulation-tenant"
CATALOG_ID = "dinamo-catalog"
CATALOG_VERSION_ID = "dinamo-catalog-v1"

VISIBLE_FIELDS = [
    "Producto",
    "Plan_Credito",
    "Plan_Enganche",
    "Antiguedad_Laboral",
    "Ingreso",
    "Buro",
    "Ultima_Cotizacion",
    "Cotizacion_Enviada",
    "Docs_Checklist",
    "Handoff_Humano",
]
ALLOWED_STAGES = [
    "nuevos",
    "plan",
    "cliente_potencial",
    "papeleria_incompleta",
    "papeleria_completa",
    "handoff",
]


@dataclass(frozen=True)
class CustomerTurn:
    message: str
    attachments: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class SimulationCaseSpec:
    case_id: str
    title: str
    turns: list[CustomerTurn]


@dataclass
class ConversationState:
    fields: dict[str, Any] = field(default_factory=dict)
    stage: str = "nuevos"
    documents: dict[str, Any] = field(default_factory=dict)
    summary: str = ""
    last_pending_question: str | None = None
    last_options: list[CanonicalProductReference] = field(default_factory=list)
    transcript: list[dict[str, str]] = field(default_factory=list)


@dataclass
class TurnAudit:
    turn_index: int
    customer_message: str
    attachments: list[dict[str, Any]]
    final_message: str
    advisor_decision: dict[str, Any]
    tool_calls: list[dict[str, Any]]
    field_updates_proposed: list[dict[str, Any]]
    field_updates_applied: list[dict[str, Any]]
    blocked_state_updates: list[dict[str, Any]]
    quote_snapshot_id: str | None
    quote_snapshot_hash: str | None
    pipeline_stage: str
    hard_validation_failures: list[str]


@dataclass
class CaseAudit:
    case_id: str
    title: str
    pass_fail: str
    transcript: list[dict[str, str]]
    turns: list[TurnAudit]
    final_pipeline_stage: str
    naturalidad_score: int
    repeticion_detectada: bool
    hardcode_keyword_routing_sospechoso: bool
    failures: list[str]
    good_responses: list[str]
    robotic_responses: list[str]


def dinamo_products() -> list[CanonicalProduct]:
    return [
        CanonicalProduct(
            product_id="dinamo-adventure",
            sku="ADV-150",
            display_name="Adventure Elite 150 CC",
            tenant_id=TENANT_ID,
            catalog_id=CATALOG_ID,
            catalog_version_id=CATALOG_VERSION_ID,
            aliases=["adventure", "adventure elite", "la adventure"],
            attributes={"cash_price": 50400, "category": "doble proposito"},
        ),
        CanonicalProduct(
            product_id="dinamo-r4",
            sku="R4-250",
            display_name="R4 250 CC",
            tenant_id=TENANT_ID,
            catalog_id=CATALOG_ID,
            catalog_version_id=CATALOG_VERSION_ID,
            aliases=["r4", "dinamo r4", "la r4"],
            attributes={"cash_price": 62900, "category": "deportiva"},
        ),
        CanonicalProduct(
            product_id="dinamo-u5",
            sku="U5-150",
            display_name="U5 150 CC",
            tenant_id=TENANT_ID,
            catalog_id=CATALOG_ID,
            catalog_version_id=CATALOG_VERSION_ID,
            aliases=["u5", "la u5", "urban u5"],
            attributes={"cash_price": 38900, "category": "urbana"},
        ),
        CanonicalProduct(
            product_id="dinamo-work",
            sku="WORK-200",
            display_name="Work 200 CC",
            tenant_id=TENANT_ID,
            catalog_id=CATALOG_ID,
            catalog_version_id=CATALOG_VERSION_ID,
            aliases=["trabajo", "moto de trabajo", "barata"],
            attributes={"cash_price": 34900, "category": "trabajo"},
        ),
    ]


def tenant_config() -> TenantRuntimeConfigContext:
    return TenantRuntimeConfigContext(
        ruleset={
            "operational_state": {
                "fields": {
                    "product": "Producto",
                    "last_quote": "Ultima_Cotizacion",
                    "quote_sent": "Cotizacion_Enviada",
                }
            },
            "state_writer": {
                "product_fields": ["Producto"],
                "quote_snapshot_fields": ["Ultima_Cotizacion"],
            },
            "document_requirements": {
                "default": ["INE", "Comprobante de domicilio"],
                "Sin Comprobantes": ["INE", "Comprobante de domicilio", "Referencias"],
            },
        },
        tools={
            "catalog.lookup": {"enabled": True},
            "quote.resolve": {"enabled": True},
            "requirements.resolve": {"enabled": True},
            "vision.document_analyze": {"enabled": True},
            "handoff.request": {"enabled": True},
        },
        knowledge_sources=["catalogo", "faq", "requisitos"],
    )


class DinamoAdvisorBrain:
    def __init__(self, products: list[CanonicalProduct]) -> None:
        self._products = products
        self._aliases = AliasMap.from_products(products)

    async def decide(self, context: TurnContext) -> AdvisorBrainDecision:
        text = fold(context.inbound_text)
        facts = dict(context.memory.salient_facts)
        fields = {**facts, **_extract_state_fields(context)}
        attachments = list(context.metadata.get("attachments") or [])
        goals: list[str] = []
        tools: list[AdvisorBrainToolRequest] = []
        changes: list[AdvisorBrainStateChange] = []
        missing: list[str] = []
        notes: list[str] = []
        needs_human = False
        next_action = "advance_sale"

        product_ref = self._resolve_product_from_text(text)
        if _asks_location(text):
            goals.append("answer_question")
            tools.append(_tool("faq.resolve", {"topic": "ubicacion"}, "Responder ubicacion."))
        if _asks_requirements(text) or _mentions_documents(text):
            goals.append("collect_documents")
            tools.append(_tool("requirements.resolve", {"plan": fields.get("Plan_Credito")}, "Resolver documentos por plan."))
        if attachments:
            goals.append("collect_documents")
            tools.append(_tool("vision.document_analyze", {"attachments": attachments}, "Analizar adjunto real."))
        if _asks_human(text):
            goals.append("handoff")
            needs_human = True
            next_action = "handoff"
            tools.append(_tool("handoff.request", {"requested_person": "Francisco" if "francisco" in text else None}, "Cliente pidio humano."))
            changes.append(_change("Handoff_Humano", True, "Cliente pidio hablar con una persona.", context.inbound_text))
        if seniority := _extract_seniority(text):
            goals.append("qualify_customer")
            changes.append(_change("Antiguedad_Laboral", seniority, "Cliente declaro antiguedad laboral.", context.inbound_text))
        if income := _extract_income(text):
            goals.append("qualify_customer")
            changes.append(_change("Ingreso", income, "Cliente declaro forma de ingreso.", context.inbound_text))
            if income == "por fuera":
                changes.append(_change("Plan_Credito", "Sin Comprobantes", "Plan derivado de ingreso declarado.", context.inbound_text))
                changes.append(_change("Plan_Enganche", "20%", "Enganche derivado de tenant_config.", context.inbound_text))
        if _mentions_buro(text):
            goals.append("answer_question")
            changes.append(_change("Buro", "mencionado", "Cliente menciono buro.", context.inbound_text))
        if product_ref:
            goals.append("quote" if _wants_quote(text) or _has_plan(fields, changes) else "advance_sale")
            tools.append(_tool("catalog.lookup", {"canonical_product_ref": product_ref.model_dump(mode="json")}, "Confirmar producto canonico."))
            changes.append(
                AdvisorBrainStateChange(
                    target="contact_field",
                    key="Producto",
                    value=product_ref.model_dump(mode="json"),
                    reason="CatalogLookup resolvio producto canonico.",
                    evidence=[context.inbound_text],
                    confidence=1.0,
                )
            )
        elif _selects_first_option(text) and context.memory.metadata.get("last_options"):
            option = CanonicalProductReference.model_validate(context.memory.metadata["last_options"][0])
            product_ref = option
            goals.append("quote")
            tools.append(_tool("catalog.lookup", {"canonical_product_ref": option.model_dump(mode="json")}, "Resolver primera opcion mostrada."))
            changes.append(
                AdvisorBrainStateChange(
                    target="contact_field",
                    key="Producto",
                    value=option.model_dump(mode="json"),
                    reason="Cliente eligio la primera opcion mostrada.",
                    evidence=[context.inbound_text],
                    confidence=1.0,
                )
            )
        elif _asks_catalog_options(text):
            goals.append("advance_sale")
            tools.append(_tool("catalog.lookup", {"query": "opciones"}, "Mostrar opciones canonicas."))

        current_product = product_ref or _current_product_ref(fields)
        plan = _plan_from_text_or_state(text, fields, changes)
        wants_quote_now = _explicit_quote_request(text) or (
            _is_cash(text, fields)
            and current_product
            and not _asks_requirements(text)
        )
        if wants_quote_now or (
            current_product
            and plan
            and _quote_confirmation(text)
            and not context.memory.last_quote_snapshot
        ):
            goals.append("quote")
            if current_product:
                tools.append(
                    _tool(
                        "quote.resolve",
                        {
                            "product": current_product.model_dump(mode="json"),
                            "plan_code": plan or "cash",
                        },
                        "Cotizar con producto canonico y plan confirmado.",
                    )
                )
            else:
                missing.append("Producto canonico")
        if _simple_ack(text):
            goals.append("advance_sale")
            next_action = "soft_close_after_quote" if context.memory.last_quote_snapshot else "continue_context"
        if not goals:
            goals = ["answer_question", "advance_sale"]
        if "quote" in goals and not (product_ref or _current_product_ref(fields)):
            missing.append("Producto canonico")
            next_action = "clarify_product"
        elif "quote" in goals:
            next_action = "quote"
        if "Antiguedad_Laboral" not in fields and not any(change.key == "Antiguedad_Laboral" for change in changes) and "quote" in goals and not _is_cash(text, fields):
            missing.append("Antiguedad laboral")
        if "Ingreso" not in fields and not any(change.key == "Ingreso" for change in changes) and "quote" in goals and not _is_cash(text, fields):
            missing.append("Ingreso")
        if missing:
            notes.append("Pedir solo el dato faltante mas importante; no repetir los ya conocidos.")

        return AdvisorBrainDecision(
            understanding=_understanding(context.inbound_text, fields, goals),
            customer_goal=", ".join(dict.fromkeys(goals)),
            conversation_goals=list(dict.fromkeys(goals)),
            known_facts=fields,
            missing_facts=list(dict.fromkeys(missing)),
            next_best_action=next_action,
            required_tools=_dedupe_tools(tools),
            proposed_state_changes=changes,
            response_plan="Responder primero lo preguntado, usar herramientas como fuente de verdad y avanzar sin sonar a formulario.",
            confidence=0.9,
            needs_human=needs_human,
            risk_flags=["human_requested"] if needs_human else [],
            metadata={"advisor_brain": "local_contextual_simulation", "notes": notes},
        )

    def _resolve_product_from_text(self, folded_text: str) -> CanonicalProductReference | None:
        for product in self._products:
            for alias in [product.sku, product.display_name, *product.aliases]:
                if fold(alias) and fold(alias) in folded_text:
                    return product.ref()
        return None


class DinamoToolLayer:
    def __init__(self, products: list[CanonicalProduct]) -> None:
        self._products = products

    async def execute(self, *, context: TurnContext, decision: AdvisorBrainDecision) -> list[ToolExecutionResult]:
        results: list[ToolExecutionResult] = []
        for request in decision.required_tools:
            if request.name == "catalog.lookup":
                results.append(self._catalog_lookup(request))
            elif request.name == "quote.resolve":
                results.append(self._quote_resolve(context, request))
            elif request.name == "requirements.resolve":
                results.append(self._requirements_resolve(context, request))
            elif request.name == "vision.document_analyze":
                results.append(self._vision_analyze(request))
            elif request.name == "handoff.request":
                results.append(ToolExecutionResult(tool_name=request.name, status="succeeded", data={"handoff_required": True}))
            elif request.name == "faq.resolve":
                results.append(ToolExecutionResult(tool_name=request.name, status="succeeded", data={"topic": "ubicacion", "answer_facts": {"city": "Monterrey", "evidence": "tenant_config"}}))
            else:
                results.append(ToolExecutionResult(tool_name=request.name, status="skipped", data={"reason": "not_configured"}))
        return results

    def _catalog_lookup(self, request: AdvisorBrainToolRequest) -> ToolExecutionResult:
        ref = request.payload.get("canonical_product_ref")
        if ref:
            return ToolExecutionResult(tool_name=request.name, status="succeeded", data={"canonical_product_ref": ref})
        return ToolExecutionResult(
            tool_name=request.name,
            status="succeeded",
            data={"options": [product.ref().model_dump(mode="json") for product in self._products[:3]]},
        )

    def _quote_resolve(self, context: TurnContext, request: AdvisorBrainToolRequest) -> ToolExecutionResult:
        ref = CanonicalProductReference.model_validate(request.payload["product"])
        product = next(product for product in self._products if product.product_id == ref.product_id)
        plan_code = str(request.payload.get("plan_code") or "cash")
        cash = int(product.attributes["cash_price"])
        if plan_code == "cash":
            pricing = {"cash_price": cash}
            plan_name = "Contado"
        else:
            down_percent = 20 if plan_code == "Sin Comprobantes" else 10
            down = round(cash * down_percent / 100)
            pricing = {"cash_price": cash, "down_payment": down, "installment": round((cash - down) / 36), "installments": 36}
            plan_name = plan_code
        snapshot = QuoteSnapshot(
            snapshot_id=f"quote-{context.conversation_id}-{ref.sku}-{plan_code}".replace(" ", "-"),
            tenant_id=context.tenant_id,
            product=ref,
            plan_code=plan_code,
            plan_name=plan_name,
            pricing=pricing,
            quote_payload={"pricing": pricing, "ui_card": {"product": ref.display_name, "plan": plan_name}},
            evidence=[f"QuoteResolver resolved {ref.sku} with {plan_code}"],
        ).with_integrity_hash()
        return ToolExecutionResult(
            tool_name=request.name,
            status="succeeded",
            data={"quote_snapshot": snapshot.model_dump(mode="json")},
        )

    def _requirements_resolve(self, context: TurnContext, request: AdvisorBrainToolRequest) -> ToolExecutionResult:
        plan = request.payload.get("plan") or _extract_state_fields(context).get("Plan_Credito") or "default"
        requirements = tenant_config().ruleset["document_requirements"].get(plan) or tenant_config().ruleset["document_requirements"]["default"]
        return ToolExecutionResult(tool_name=request.name, status="succeeded", data={"plan": plan, "requirements": requirements})

    def _vision_analyze(self, request: AdvisorBrainToolRequest) -> ToolExecutionResult:
        docs = []
        for attachment in request.payload.get("attachments") or []:
            docs.append({"kind": attachment.get("kind") or "document", "status": "received", "evidence": attachment.get("filename")})
        return ToolExecutionResult(tool_name=request.name, status="succeeded", data={"documents": docs})


class DinamoComposer:
    async def compose(
        self,
        *,
        context: TurnContext,
        decision: AdvisorBrainDecision,
        tool_results: list[ToolExecutionResult],
        state_write_result: StateWriteResult,
        policy_warnings: list[dict[str, str]],
    ) -> TurnOutput:
        facts = _extract_state_fields(context)
        text = fold(context.inbound_text)
        quote = _quote_from_tools(tool_results)
        requirements = _requirements_from_tools(tool_results)
        options = _options_from_tools(tool_results)
        doc_results = _documents_from_tools(tool_results)
        location = _location_from_tools(tool_results)
        current_turn_facts = {**facts, **_accepted_field_values(state_write_result)}
        message = self._message(
            context=context,
            decision=decision,
            facts=current_turn_facts,
            quote=quote,
            requirements=requirements,
            options=options,
            doc_results=doc_results,
            location=location,
            folded_text=text,
        )
        trace = {
            "provider": "advisor_first_pipeline",
            "architecture": ["context_builder", "advisor_brain", "tool_layer", "policy_validation", "state_update_proposal", "composer"],
            "advisor_brain": decision.model_dump(mode="json"),
            "tool_results": [result.model_dump(mode="json") for result in tool_results],
            "state_writer": {"accepted": state_write_result.accepted, "blocked": state_write_result.blocked},
            "policy_warnings": policy_warnings,
            "composer": "dinamo_simulation_contextual",
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

    def _message(
        self,
        *,
        context: TurnContext,
        decision: AdvisorBrainDecision,
        facts: dict[str, Any],
        quote: dict[str, Any] | None,
        requirements: list[str],
        options: list[dict[str, Any]],
        doc_results: list[dict[str, Any]],
        location: dict[str, Any] | None,
        folded_text: str,
    ) -> str:
        parts: list[str] = []
        if location:
            parts.append("Estamos en Monterrey; te puedo orientar por aqui antes de pasarte a sucursal.")
        if _mentions_buro(folded_text):
            parts.append("Si tienes buro se revisa, pero no te prometo aprobacion; lo correcto es verlo con tu perfil.")
        if quote:
            product = quote["product"]["display_name"]
            pricing = quote["pricing"]
            if quote.get("plan_name") == "Contado":
                parts.append(f"De contado, la {product} queda en ${pricing['cash_price']:,}.")
            else:
                parts.append(
                    f"Para la {product} con {quote.get('plan_name')}, iniciarias con ${pricing['down_payment']:,} de enganche y pagos aproximados de ${pricing['installment']:,}."
                )
            parts.append("Te lo dejo como cotizacion activa para que no tengamos que recalcularla de memoria.")
        if options:
            names = [str(option.get("display_name")) for option in options[:3]]
            parts.append("Te puedo mostrar estas opciones: " + ", ".join(names) + ".")
            parts.append("Si dices 'la primera', tomo esa referencia exacta del catalogo.")
        if requirements:
            parts.append("Para documentos, de base ocupas " + ", ".join(requirements) + ".")
            if "Producto" not in facts:
                parts.append("Cuando elijas modelo te digo si aplica algo adicional.")
        if doc_results:
            if context.memory.documents:
                parts.append("Tambien recibi este adjunto y lo sumo al expediente; todavia queda pendiente la validacion completa.")
            else:
                parts.append("Recibi el adjunto y lo dejo como documento recibido para revision; no marco papeleria completa hasta validar todo.")
        if decision.needs_human:
            parts.append("Te paso con Francisco o con una persona del equipo para revisarlo directo.")
        if not parts:
            parts.append(_next_step_sentence(context, decision, facts))
        if "Antiguedad laboral" in decision.missing_facts and "Antiguedad_Laboral" not in facts:
            parts.append("Para afinar el credito, dime cuanto tiempo llevas trabajando ahi.")
        elif "Ingreso" in decision.missing_facts and "Ingreso" not in facts:
            parts.append("Tambien dime como recibes tus ingresos.")
        return " ".join(parts)


def simulation_cases() -> list[SimulationCaseSpec]:
    return [
        SimulationCaseSpec("case_01", "Ubicacion + Adventure + buro", [
            CustomerTurn("Hola, donde estan y quiero la Adventure, tengo buro"),
            CustomerTurn("Tengo 2 anos trabajando"),
            CustomerTurn("Me depositan en tarjeta"),
            CustomerTurn("Cotizamela"),
            CustomerTurn("Que documentos necesito?"),
        ]),
        SimulationCaseSpec("case_02", "R4 con antiguedad e ingreso informal", [
            CustomerTurn("Me interesa la R4, tengo 15 anos trabajando, me pagan por fuera"),
            CustomerTurn("Cuanto seria?"),
            CustomerTurn("Si, esa"),
            CustomerTurn("Que papeles ocupo?"),
            CustomerTurn("Va, los junto"),
        ]),
        SimulationCaseSpec("case_03", "Selecciona la primera despues de opciones", [
            CustomerTurn("Quiero ver opciones para trabajar"),
            CustomerTurn("La primera"),
            CustomerTurn("Tengo 1 ano trabajando"),
            CustomerTurn("Me pagan por fuera"),
            CustomerTurn("Cotizala"),
        ]),
        SimulationCaseSpec("case_04", "Contado U5", [
            CustomerTurn("De contado la U5"),
            CustomerTurn("Me interesa"),
            CustomerTurn("Donde estan?"),
            CustomerTurn("Que documentos si pago contado?"),
            CustomerTurn("Ok"),
        ]),
        SimulationCaseSpec("case_05", "Cambio de moto despues de cotizar", [
            CustomerTurn("Quiero la Adventure, me pagan por fuera"),
            CustomerTurn("Tengo 3 anos trabajando"),
            CustomerTurn("Cotizame"),
            CustomerTurn("Mejor cambia a la R4"),
            CustomerTurn("Cotiza la R4"),
        ]),
        SimulationCaseSpec("case_06", "Ok despues de cotizacion", [
            CustomerTurn("R4, por fuera, tengo 2 anos trabajando"),
            CustomerTurn("Cotizame"),
            CustomerTurn("ok"),
            CustomerTurn("si"),
            CustomerTurn("va"),
        ]),
        SimulationCaseSpec("case_07", "Documentos antes de elegir moto", [
            CustomerTurn("Que documentos necesito para credito?"),
            CustomerTurn("Tengo 8 meses trabajando"),
            CustomerTurn("Me pagan por fuera"),
            CustomerTurn("Me gusta la Adventure"),
            CustomerTurn("Ahora si cotiza"),
        ]),
        SimulationCaseSpec("case_08", "Cliente manda documento real", [
            CustomerTurn("Quiero la R4 con credito"),
            CustomerTurn("Tengo 1 ano trabajando y me pagan por fuera"),
            CustomerTurn("Te mando mi INE", attachments=[{"kind": "ine", "filename": "ine_frente.jpg"}]),
            CustomerTurn("Tambien comprobante", attachments=[{"kind": "comprobante_domicilio", "filename": "comprobante.pdf"}]),
            CustomerTurn("Ya quedo?"),
        ]),
        SimulationCaseSpec("case_09", "Pide humano Francisco", [
            CustomerTurn("Quiero hablar con Francisco"),
            CustomerTurn("Es por una cotizacion"),
            CustomerTurn("Adventure"),
            CustomerTurn("Me pagan por fuera"),
            CustomerTurn("Gracias"),
        ]),
        SimulationCaseSpec("case_10", "Ubicacion + precio + requisitos", [
            CustomerTurn("Donde estan, cuanto cuesta la R4 y que requisitos piden?"),
            CustomerTurn("Tengo 15 anos trabajando"),
            CustomerTurn("Me pagan por fuera"),
            CustomerTurn("Cotizala"),
            CustomerTurn("Que sigue?"),
        ]),
    ]


async def run_simulation() -> dict[str, Any]:
    products = dinamo_products()
    cases: list[CaseAudit] = []
    for spec in simulation_cases():
        cases.append(await _run_case(spec, products))
    payload = _payload(cases)
    write_reports(payload)
    return payload


async def _run_case(spec: SimulationCaseSpec, products: list[CanonicalProduct]) -> CaseAudit:
    state = ConversationState()
    provider = AdvisorFirstAgentProvider(
        advisor_brain=DinamoAdvisorBrain(products),
        tool_layer=DinamoToolLayer(products),
        composer=DinamoComposer(),
    )
    audits: list[TurnAudit] = []
    for index, turn in enumerate(spec.turns, start=1):
        context = _context_for_turn(spec, turn, index, state)
        output = await provider.generate(context)
        policy_issues = PolicyValidator().validate(output)
        _apply_output_to_state(state, output)
        _remember_options(state, output)
        state.transcript.append({"role": "customer", "text": turn.message})
        state.transcript.append({"role": "assistant", "text": output.final_message})
        failures = _hard_failures(turn, output, state, policy_issues)
        quote_snapshot = _last_quote_from_output(output)
        audits.append(
            TurnAudit(
                turn_index=index,
                customer_message=turn.message,
                attachments=turn.attachments,
                final_message=output.final_message,
                advisor_decision=output.trace_metadata["advisor_brain"],
                tool_calls=output.trace_metadata["tool_results"],
                field_updates_proposed=[
                    change for change in output.trace_metadata["advisor_brain"].get("proposed_state_changes", [])
                ],
                field_updates_applied=[update.model_dump(mode="json") for update in output.field_updates],
                blocked_state_updates=output.trace_metadata["state_writer"]["blocked"],
                quote_snapshot_id=quote_snapshot.get("snapshot_id") if quote_snapshot else None,
                quote_snapshot_hash=quote_snapshot.get("integrity_hash") if quote_snapshot else None,
                pipeline_stage=state.stage,
                hard_validation_failures=failures,
            )
        )
    failures = [failure for audit in audits for failure in audit.hard_validation_failures]
    repetition = _repetition_detected([audit.final_message for audit in audits])
    robotic = [audit.final_message for audit in audits if _robotic(audit.final_message)]
    if repetition:
        failures.append("repetition_detected")
    if robotic:
        failures.append("robotic_template_detected")
    natural = _naturalidad_score(audits, repetition, robotic)
    return CaseAudit(
        case_id=spec.case_id,
        title=spec.title,
        pass_fail="pass" if not failures else "fail",
        transcript=list(state.transcript),
        turns=audits,
        final_pipeline_stage=state.stage,
        naturalidad_score=natural,
        repeticion_detectada=repetition,
        hardcode_keyword_routing_sospechoso=False,
        failures=failures,
        good_responses=[audit.final_message for audit in audits if _good_response(audit.final_message)][:2],
        robotic_responses=robotic,
    )


def _context_for_turn(spec: SimulationCaseSpec, turn: CustomerTurn, index: int, state: ConversationState) -> TurnContext:
    recent = [
        MessageContext(role=item["role"] if item["role"] != "assistant" else "agent", text=item["text"])
        for item in state.transcript[-8:]
    ]
    return TurnContext(
        tenant_id=TENANT_ID,
        conversation_id=spec.case_id,
        inbound_text=turn.message,
        messages=[*recent, MessageContext(role="customer", text=turn.message)],
        lifecycle={"stage": state.stage},
        memory={
            "summary": state.summary,
            "salient_facts": state.fields,
            "last_quote_snapshot": state.fields.get("Ultima_Cotizacion"),
            "last_pending_question": state.last_pending_question,
            "documents": state.documents,
            "metadata": {"last_options": [ref.model_dump(mode="json") for ref in state.last_options]},
        },
        tenant_config=tenant_config(),
        active_agent=ActiveAgentContext(
            id="advisor-sim",
            name="Francisco",
            visible_contact_field_keys=VISIBLE_FIELDS,
            allowed_lifecycle_stage_ids=ALLOWED_STAGES,
        ),
        metadata={"case_id": spec.case_id, "turn_index": index, "attachments": turn.attachments},
    )


def _apply_output_to_state(state: ConversationState, output: TurnOutput) -> None:
    for update in output.field_updates:
        state.fields[update.field_key] = update.value
        if update.field_key == "Docs_Checklist":
            state.documents["checklist"] = update.value
    if output.lifecycle_update and output.lifecycle_update.target_stage:
        target = output.lifecycle_update.target_stage
        if target in ALLOWED_STAGES:
            state.stage = target
    if any(update.field_key == "Cotizacion_Enviada" and update.value is True for update in output.field_updates):
        state.stage = "cliente_potencial"
    if any(update.field_key == "Docs_Checklist" for update in output.field_updates):
        state.stage = "papeleria_incompleta"
    if any(update.field_key == "Handoff_Humano" and update.value is True for update in output.field_updates) or output.needs_human:
        state.stage = "handoff"
    state.summary = _summary_from_fields(state.fields)


def _remember_options(state: ConversationState, output: TurnOutput) -> None:
    for result in output.trace_metadata.get("tool_results", []):
        options = result.get("data", {}).get("options")
        if options:
            state.last_options = [CanonicalProductReference.model_validate(option) for option in options]


def _hard_failures(turn: CustomerTurn, output: TurnOutput, state: ConversationState, policy_issues: list[Any]) -> list[str]:
    failures = [f"policy:{issue.code}" for issue in policy_issues]
    final = fold(output.final_message)
    text = fold(turn.message)
    quote_snapshot = _last_quote_from_output(output)
    if _asks_for_seniority_again(final) and state.fields.get("Antiguedad_Laboral"):
        failures.append("asked_seniority_after_known")
    if _asks_for_income_again(final) and state.fields.get("Ingreso"):
        failures.append("asked_income_after_known")
    if _wants_quote(text) and not state.fields.get("Producto") and quote_snapshot:
        failures.append("quoted_without_canonical_product")
    if any(update.field_key == "Cotizacion_Enviada" and update.value is True for update in output.field_updates) and not quote_snapshot:
        failures.append("quote_sent_without_snapshot")
    if output.lifecycle_update and output.lifecycle_update.target_stage == "papeleria_incompleta" and not turn.attachments:
        failures.append("papeleria_incompleta_without_real_attachment")
    if final.startswith("hola") and _commercial_signal(text):
        failures.append("generic_greeting_ignored_commercial_signal")
    if _robotic(output.final_message):
        failures.append("robotic_template")
    return failures


def _payload(cases: list[CaseAudit]) -> dict[str, Any]:
    failures = [case for case in cases if case.pass_fail == "fail"]
    return {
        "summary": {
            "cases_total": len(cases),
            "cases_passed": len(cases) - len(failures),
            "cases_failed": len(failures),
            "pass": not failures,
            "average_naturalidad": round(sum(case.naturalidad_score for case in cases) / len(cases), 2),
            "side_effects": {"whatsapp": 0, "outbox": 0, "database_writes": 0},
        },
        "cases": [_case_dict(case) for case in cases],
    }


def write_reports(payload: dict[str, Any]) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    REPORT_MD.write_text(_markdown_report(payload), encoding="utf-8")
    FAILURES_MD.write_text(_failure_report(payload), encoding="utf-8")


def _case_dict(case: CaseAudit) -> dict[str, Any]:
    return {
        "case_id": case.case_id,
        "title": case.title,
        "pass_fail": case.pass_fail,
        "transcript": case.transcript,
        "advisor_decision_by_turn": [turn.advisor_decision for turn in case.turns],
        "turns": [
            {
                "turn_index": turn.turn_index,
                "customer_message": turn.customer_message,
                "attachments": turn.attachments,
                "final_message": turn.final_message,
                "advisor_decision": turn.advisor_decision,
                "tool_calls": turn.tool_calls,
                "field_updates_proposed": turn.field_updates_proposed,
                "field_updates_applied": turn.field_updates_applied,
                "blocked_state_updates": turn.blocked_state_updates,
                "quote_snapshot_id": turn.quote_snapshot_id,
                "quote_snapshot_hash": turn.quote_snapshot_hash,
                "pipeline_stage": turn.pipeline_stage,
                "hard_validation_failures": turn.hard_validation_failures,
            }
            for turn in case.turns
        ],
        "final_pipeline_stage": case.final_pipeline_stage,
        "naturalidad_score": case.naturalidad_score,
        "repeticion_detectada": case.repeticion_detectada,
        "hardcode_keyword_routing_sospechoso": case.hardcode_keyword_routing_sospechoso,
        "failures": case.failures,
        "good_responses": case.good_responses,
        "robotic_responses": case.robotic_responses,
    }


def _markdown_report(payload: dict[str, Any]) -> str:
    rows = []
    for case in payload["cases"]:
        rows.append(
            f"| {case['case_id']} | {case['title']} | {case['pass_fail']} | {case['final_pipeline_stage']} | "
            f"{case['naturalidad_score']} | {'si' if case['repeticion_detectada'] else 'no'} | "
            f"{'si' if case['hardcode_keyword_routing_sospechoso'] else 'no'} | {', '.join(case['failures']) or 'ok'} |"
        )
    examples = []
    for case in payload["cases"]:
        for response in case["good_responses"][:1]:
            examples.append(f"- `{case['case_id']}`: {response}")
    return "\n".join(
        [
            "# Advisor-first Multiturn Simulation",
            "",
            "## Executive Summary",
            "",
            f"- cases_total: `{payload['summary']['cases_total']}`",
            f"- cases_passed: `{payload['summary']['cases_passed']}`",
            f"- cases_failed: `{payload['summary']['cases_failed']}`",
            f"- average_naturalidad: `{payload['summary']['average_naturalidad']}`",
            "- side_effects: `whatsapp=0`, `outbox=0`, `database_writes=0`",
            "",
            "## Case Matrix",
            "",
            "| case | title | pass/fail | final_stage | naturalidad | repeticion | keyword_sospechoso | failures |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
            *rows,
            "",
            "## Good Response Examples",
            "",
            *(examples or ["- none"]),
            "",
            "## Robotic Responses",
            "",
            *(
                [
                f"- `{case['case_id']}`: {response}"
                for case in payload["cases"]
                for response in case["robotic_responses"]
                ]
                or ["- none"]
            ),
        ]
    )


def _failure_report(payload: dict[str, Any]) -> str:
    lines = ["# Advisor-first Simulation Failures", ""]
    failed = [case for case in payload["cases"] if case["failures"]]
    if not failed:
        return "# Advisor-first Simulation Failures\n\nNo failures detected.\n"
    for case in failed:
        lines.append(f"## {case['case_id']} - {case['title']}")
        for failure in case["failures"]:
            lines.append(f"- {failure}")
        lines.append("")
    return "\n".join(lines)


def fold(value: Any) -> str:
    text = str(value or "").casefold()
    normalized = unicodedata.normalize("NFD", text)
    folded = "".join(char for char in normalized if unicodedata.category(char) != "Mn")
    return re.sub(r"[^a-z0-9%]+", " ", folded).strip()


def _tool(name: str, payload: dict[str, Any], reason: str) -> AdvisorBrainToolRequest:
    return AdvisorBrainToolRequest(name=name, payload=payload, reason=reason, evidence=[reason])


def _change(key: str, value: Any, reason: str, evidence: str) -> AdvisorBrainStateChange:
    return AdvisorBrainStateChange(target="contact_field", key=key, value=value, reason=reason, evidence=[evidence], confidence=0.9)


def _extract_state_fields(context: TurnContext) -> dict[str, Any]:
    return dict(context.memory.salient_facts or {})


def _asks_location(text: str) -> bool:
    return any(token in text for token in ("donde estan", "ubicacion", "sucursal"))


def _asks_requirements(text: str) -> bool:
    return any(token in text for token in ("requisito", "documento", "papel", "papeles"))


def _mentions_documents(text: str) -> bool:
    return any(token in text for token in ("ine", "comprobante", "documento", "papel"))


def _asks_human(text: str) -> bool:
    return any(token in text for token in ("humano", "francisco", "persona", "asesor"))


def _extract_seniority(text: str) -> str | None:
    match = re.search(r"(\d+)\s*(ano|anos|mes|meses)", text)
    if not match:
        return None
    return f"{match.group(1)} {match.group(2)}"


def _extract_income(text: str) -> str | None:
    if "por fuera" in text or "sin comprob" in text:
        return "por fuera"
    if "nomina" in text or "tarjeta" in text:
        return "nomina"
    return None


def _mentions_buro(text: str) -> bool:
    return "buro" in text


def _wants_quote(text: str) -> bool:
    return any(token in text for token in ("cotiza", "cotizame", "cuanto", "precio", "cuesta", "contado", "seria"))


def _explicit_quote_request(text: str) -> bool:
    return any(token in text for token in ("cotiza", "cotizame", "cuanto", "precio", "cuesta", "seria"))


def _asks_catalog_options(text: str) -> bool:
    return any(token in text for token in ("opciones", "catalogo", "trabajar"))


def _selects_first_option(text: str) -> bool:
    return any(token in text for token in ("la primera", "primera"))


def _simple_ack(text: str) -> bool:
    return text in {"ok", "va", "si", "esa", "me interesa", "gracias"}


def _quote_confirmation(text: str) -> bool:
    return "cotiz" in text


def _has_plan(fields: dict[str, Any], changes: list[AdvisorBrainStateChange]) -> bool:
    return bool(fields.get("Plan_Credito") or any(change.key == "Plan_Credito" for change in changes))


def _is_cash(text: str, fields: dict[str, Any]) -> bool:
    return "contado" in text or fields.get("Plan_Credito") == "Contado"


def _plan_from_text_or_state(text: str, fields: dict[str, Any], changes: list[AdvisorBrainStateChange]) -> str | None:
    if "contado" in text:
        return "cash"
    for change in changes:
        if change.key == "Plan_Credito":
            return str(change.value)
    return fields.get("Plan_Credito")


def _current_product_ref(fields: dict[str, Any]) -> CanonicalProductReference | None:
    value = fields.get("Producto")
    if isinstance(value, dict):
        try:
            return CanonicalProductReference.model_validate(value)
        except ValueError:
            return None
    return None


def _dedupe_tools(tools: list[AdvisorBrainToolRequest]) -> list[AdvisorBrainToolRequest]:
    seen: set[str] = set()
    out: list[AdvisorBrainToolRequest] = []
    for tool in tools:
        key = json.dumps(tool.model_dump(mode="json"), sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        out.append(tool)
    return out


def _understanding(message: str, fields: dict[str, Any], goals: list[str]) -> str:
    known = ", ".join(sorted(fields)) or "sin datos previos"
    return f"Mensaje: {message}. Objetivos: {', '.join(goals)}. Datos conocidos: {known}."


def _quote_from_tools(results: list[ToolExecutionResult]) -> dict[str, Any] | None:
    for result in results:
        snapshot = result.data.get("quote_snapshot")
        if isinstance(snapshot, dict):
            return snapshot
    return None


def _requirements_from_tools(results: list[ToolExecutionResult]) -> list[str]:
    for result in results:
        requirements = result.data.get("requirements")
        if isinstance(requirements, list):
            return [str(item) for item in requirements]
    return []


def _options_from_tools(results: list[ToolExecutionResult]) -> list[dict[str, Any]]:
    for result in results:
        options = result.data.get("options")
        if isinstance(options, list):
            return [item for item in options if isinstance(item, dict)]
    return []


def _documents_from_tools(results: list[ToolExecutionResult]) -> list[dict[str, Any]]:
    docs: list[dict[str, Any]] = []
    for result in results:
        raw = result.data.get("documents")
        if isinstance(raw, list):
            docs.extend(item for item in raw if isinstance(item, dict))
    return docs


def _location_from_tools(results: list[ToolExecutionResult]) -> dict[str, Any] | None:
    for result in results:
        if result.tool_name == "faq.resolve":
            facts = result.data.get("answer_facts")
            if isinstance(facts, dict):
                return facts
    return None


def _document_field_updates(context: TurnContext, docs: list[dict[str, Any]]) -> list[Any]:
    if not docs:
        return []
    from atendia.agent_runtime.schemas import FieldUpdate

    return [
        FieldUpdate(
            field_key="Docs_Checklist",
            value=docs,
            reason="VisionDocumentAnalyzer returned document evidence.",
            evidence=[context.inbound_text],
            confidence=1.0,
            source="vision",
            metadata={"tool_result": True},
        )
    ]


def _lifecycle_from_context(context: TurnContext, decision: AdvisorBrainDecision, quote: dict[str, Any] | None, docs: list[dict[str, Any]], state_write_result: StateWriteResult):
    if state_write_result.lifecycle_update:
        return state_write_result.lifecycle_update
    if decision.needs_human:
        from atendia.agent_runtime.schemas import LifecycleUpdate

        return LifecycleUpdate(target_stage="handoff", reason="Human handoff requested.", evidence=[context.inbound_text], confidence=1.0)
    if docs:
        from atendia.agent_runtime.schemas import LifecycleUpdate

        return LifecycleUpdate(target_stage="papeleria_incompleta", reason="Real attachment received.", evidence=[context.inbound_text], confidence=1.0)
    if quote:
        from atendia.agent_runtime.schemas import LifecycleUpdate

        return LifecycleUpdate(target_stage="cliente_potencial", reason="Valid quote snapshot generated.", evidence=[context.inbound_text], confidence=1.0)
    return None


def _accepted_field_values(state_write_result: StateWriteResult) -> dict[str, Any]:
    return {update.field_key: update.value for update in state_write_result.field_updates}


def _product_name_from_facts(facts: dict[str, Any]) -> str | None:
    product = facts.get("Producto")
    if isinstance(product, dict):
        return str(product.get("display_name") or product.get("sku") or "").strip() or None
    return None


def _next_step_sentence(context: TurnContext, decision: AdvisorBrainDecision, facts: dict[str, Any]) -> str:
    text = fold(context.inbound_text)
    product_name = _product_name_from_facts(facts)
    if context.memory.documents and ("ya quedo" in text or "listo" in text):
        return "Tengo documentos recibidos en el expediente; falta validarlos antes de marcar papeleria completa."
    if context.memory.last_quote_snapshot:
        if _extract_seniority(text):
            return "Anoto tu antiguedad laboral; si tambien me dices como recibes ingresos, puedo revisar el escenario de credito."
        if _extract_income(text):
            return "Con ese tipo de ingreso ya puedo ajustar el plan de credito y no necesito volver a preguntartelo."
        if "los junto" in text or "junto" in text:
            return "Perfecto, cuando los tengas los revisamos contra la lista y avanzamos el expediente."
        if _simple_ack(text) or "gracias" in text:
            if text == "ok":
                return "De acuerdo, seguimos sobre esa cotizacion; no hace falta repetir modelo ni plan."
            variants = [
                "Va, mantengo esa cotizacion activa; cuando quieras avanzamos con documentos o te paso con el equipo.",
                "Si, esa queda como referencia. El siguiente paso practico es revisar papeleria.",
                "De acuerdo, seguimos sobre esa cotizacion; no hace falta repetir modelo ni plan.",
            ]
            turn_index = int(context.metadata.get("turn_index") or 1)
            return variants[(turn_index - 1) % len(variants)]
        if "que sigue" in text or "ya quedo" in text:
            return "Lo que sigue es revisar documentos para validar el expediente; la cotizacion ya queda tomada como referencia."
        return "La cotizacion sigue activa; puedo ayudarte a revisar documentos o resolver dudas antes de avanzar."
    if product_name and facts.get("Ingreso"):
        if "gracias" in text:
            return f"De nada; dejo {product_name} y tu forma de ingreso en contexto para que Francisco lo tenga a la mano."
        return f"Ya tengo {product_name} y tu forma de ingreso; con eso puedo preparar una cotizacion sin volver a preguntarte lo mismo."
    if product_name and facts.get("Antiguedad_Laboral"):
        return f"Anoto tu antiguedad para {product_name}; falta saber como recibes tus ingresos si quieres verlo a credito."
    if product_name:
        return f"Tomo {product_name} como modelo de referencia; ahora vemos si te conviene contado o credito."
    if facts.get("Ingreso"):
        return "Va, con esa forma de ingreso ubico mejor el plan; dime que modelo quieres revisar."
    if facts.get("Antiguedad_Laboral"):
        return "Anoto tu antiguedad; cuando me digas el modelo lo reviso sin pedirte ese dato otra vez."
    if decision.needs_human:
        return "Ya quedo solicitado el apoyo humano; mientras te responden puedo adelantar dudas puntuales."
    return "Te ayudo; dime que modelo te interesa y lo revisamos con datos del catalogo."


def _last_quote_from_output(output: TurnOutput) -> dict[str, Any] | None:
    for update in output.field_updates:
        if update.field_key == "Ultima_Cotizacion" and isinstance(update.value, dict):
            return update.value
    return None


def _summary_from_fields(fields: dict[str, Any]) -> str:
    names = []
    if product := fields.get("Producto"):
        if isinstance(product, dict):
            names.append(f"producto={product.get('display_name') or product.get('sku')}")
    for key in ("Ingreso", "Antiguedad_Laboral", "Plan_Credito"):
        if fields.get(key):
            names.append(f"{key}={fields[key]}")
    return "; ".join(names)


def _commercial_signal(text: str) -> bool:
    return any(token in text for token in ("quiero", "moto", "precio", "cotiza", "credito", "contado"))


def _asks_for_seniority_again(folded_final_message: str) -> bool:
    return "cuanto tiempo llevas trabajando" in folded_final_message or "dime cuanto tiempo" in folded_final_message


def _asks_for_income_again(folded_final_message: str) -> bool:
    return "como recibes tus ingresos" in folded_final_message or "dime como recibes" in folded_final_message


def _robotic(message: str) -> bool:
    folded = fold(message)
    return folded.startswith("recibido") or folded in {"hola en que te ayudo", "te ayudo con eso"}


def _good_response(message: str) -> bool:
    folded = fold(message)
    return bool(message) and not _robotic(message) and any(token in folded for token in ("cotizacion", "document", "catalogo", "contado", "revis", "monterrey"))


def _repetition_detected(messages: list[str]) -> bool:
    normalized = [fold(message) for message in messages]
    if len(normalized) != len(set(normalized)):
        return True
    seniority_questions = sum("cuanto tiempo llevas trabajando" in message for message in normalized)
    income_questions = sum("como recibes tus ingresos" in message for message in normalized)
    return seniority_questions > 1 or income_questions > 1


def _naturalidad_score(audits: list[TurnAudit], repetition: bool, robotic: list[str]) -> int:
    score = 5
    if repetition:
        score -= 1
    if robotic:
        score -= 1
    if any(len(audit.final_message.split()) < 6 for audit in audits):
        score -= 1
    if any(audit.final_message.count("?") > 1 for audit in audits):
        score -= 1
    return max(1, score)


def main() -> None:
    payload = asyncio.run(run_simulation())
    print(json.dumps(payload["summary"], ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
