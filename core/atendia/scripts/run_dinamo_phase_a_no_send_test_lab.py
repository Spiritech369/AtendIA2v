"""Run Dinamo Phase A direct Test Lab without OpenAI or external APIs.

This script stores DB-backed Test Lab suites/scenarios for the Dinamo tenant
and executes them through the Respond-Style direct no-send runtime using a
deterministic local provider. It never calls OpenAI, never sends, never writes
outbox rows, and never executes workflow/action side effects.

Usage:
    PYTHONPATH=. uv run python -m atendia.scripts.run_dinamo_phase_a_no_send_test_lab \
        --tenant-id <uuid>
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.agent_runtime.respond_style_dry_facts_executor import DryFactsToolExecutor
from atendia.agent_runtime.respond_style_tool_loop import (
    RespondStyleToolLoop,
    RespondStyleToolLoopConfig,
)
from atendia.agent_runtime.respond_style_turn_contract import (
    AgentContextPackage,
    AgentTurnInput,
    AgentTurnValidationResult,
    FinalTurnDecision,
    LLMFieldUpdateProposal,
    LLMHandoffProposal,
    LLMToolCallProposal,
    LLMWorkflowEventProposal,
    ValidationErrorItem,
)
from atendia.db.models.agent import Agent
from atendia.db.models.outbound_outbox import OutboundOutbox
from atendia.db.models.product_agent import AgentDeployment, AgentTestRun, AgentVersion
from atendia.db.session import get_db_session
from atendia.product_agents import service, test_lab_direct_adapter
from atendia.product_agents.test_lab_direct_adapter import (
    DIRECT_DECISION_BLOCKED,
    DIRECT_DECISION_READY,
)
from atendia.scripts.seed_dinamo_v1 import AGENT_NAME, PLAN_CREDITO_CHOICES, SEED_ID

JsonDict = dict[str, Any]

PLAN_NOMINA_TARJETA = PLAN_CREDITO_CHOICES[0]
PLAN_SIN_COMPROBANTES = PLAN_CREDITO_CHOICES[4]
PLAN_GUARDIA = PLAN_CREDITO_CHOICES[5]


@dataclass(frozen=True)
class PhaseAScenario:
    key: str
    name: str
    turns: tuple[str, ...]
    expected_tools: tuple[str, ...] = ()
    expected_fields: tuple[str, ...] = ()
    forbidden_fields: tuple[str, ...] = ("Autorizado", "Plan_Enganche")
    expected_workflows: tuple[str, ...] = ()
    expected_handoff_reason: str | None = None
    expected_blocked: bool = False
    final_message_contains: tuple[str, ...] = ()
    forbidden_final_message_contains: tuple[str, ...] = (
        "/goal",
        "trace",
        "tool",
        "workflow",
        "StateWriter",
        "te paso con Francisco",
        "te paso con Frank",
    )

    def as_expected(self) -> JsonDict:
        return {
            "expected_tools": list(self.expected_tools),
            "expected_fields": list(self.expected_fields),
            "forbidden_fields": list(self.forbidden_fields),
            "expected_workflows": list(self.expected_workflows),
            "expected_handoff_reason": self.expected_handoff_reason,
            "expected_blocked": self.expected_blocked,
            "final_message_contains": list(self.final_message_contains),
            "forbidden_final_message_contains": list(
                self.forbidden_final_message_contains
            ),
        }


@dataclass
class PhaseATestLabResult:
    tenant_id: str
    negative_suite_id: str
    negative_run_id: str
    readiness_suite_id: str
    readiness_run_id: str
    readiness_status: str
    readiness_decision: str
    readiness_pass_count: int
    readiness_blocked_count: int
    outbox_before: int
    outbox_after: int
    outbox_delta: int
    deployments_no_send: bool
    assertions: list[str] = field(default_factory=list)

    def as_dict(self) -> JsonDict:
        return {
            "tenant_id": self.tenant_id,
            "negative_suite_id": self.negative_suite_id,
            "negative_run_id": self.negative_run_id,
            "readiness_suite_id": self.readiness_suite_id,
            "readiness_run_id": self.readiness_run_id,
            "readiness_status": self.readiness_status,
            "readiness_decision": self.readiness_decision,
            "readiness_pass_count": self.readiness_pass_count,
            "readiness_blocked_count": self.readiness_blocked_count,
            "outbox_before": self.outbox_before,
            "outbox_after": self.outbox_after,
            "outbox_delta": self.outbox_delta,
            "deployments_no_send": self.deployments_no_send,
            "assertions": self.assertions,
            "openai_api_real": False,
            "external_apis": False,
            "send": "no_send",
        }


class DeterministicDinamoPhaseAProvider:
    """Local Test Lab provider for Dinamo preflight.

    It returns structured turn decisions only. Customer-visible text is included
    solely as a no-send simulated candidate captured by Test Lab evidence.
    """

    async def generate(
        self,
        *,
        turn_input: AgentTurnInput,
        context: AgentContextPackage,
    ) -> FinalTurnDecision:
        text = _fold(turn_input.inbound_text)
        tool_names = _tool_names(context)

        if "autorizado" in text or "cerrado ganado" in text:
            return _blocked_decision("human_admin_only_field_attempt")
        if "apruebamelo sin revisar" in text or "sin revisar" in text:
            return _blocked_decision("unsupported_approval_claim")
        if "ya pague" in text or "ya pagué" in text:
            return _handoff_decision(
                reason="pago_reportado",
                message=(
                    "Eso lo reviso directo antes de mover cualquier dato. "
                    "Dame un momento y te confirmo por aqui."
                ),
            )
        if "humano" in text or "persona" in text:
            return _handoff_decision(
                reason="humano_solicitado",
                message="Dejame revisarlo bien y te confirmo por aqui en un momento.",
            )
        if "2 meses" in text or "dos meses" in text:
            return _valid_decision(
                final_message=(
                    "Por ahora los planes para trabajadores menores a 6 meses "
                    "estan deshabilitados. Cuando cumplas los 6 meses lo revisamos."
                ),
                fields=[
                    _field("Cumple_Antiguedad", False, "Cliente declaro 2 meses.")
                ],
                workflows=[
                    _workflow("pipeline.transition", "field_updated", {"stage": "no_califica"})
                ],
                phase="no_califica",
            )
        if "menos quincenas" in text or "1 ano" in text or "un ano" in text:
            return _tool_then_final(
                tool_names=tool_names,
                tool="faq.lookup",
                arguments={"question": "plazo 72 quincenas liquidacion anticipada"},
                final_message=(
                    "El esquema es de 72 quincenas. Puedes preguntar por "
                    "liquidacion anticipada, pero no negocio menos quincenas por aqui."
                ),
                phase="plazo_fijo",
            )
        if "sin comprobantes" in text:
            return _tool_then_final(
                tool_names=tool_names,
                tool="requirements.lookup",
                arguments={"Plan_Credito": PLAN_SIN_COMPROBANTES},
                final_message=(
                    "Para sin comprobantes revisamos INE y comprobante de domicilio. "
                    "Tambien necesito saber que moto te interesa."
                ),
                fields=[
                    _field(
                        "Plan_Credito",
                        PLAN_SIN_COMPROBANTES,
                        "Cliente pidio el plan sin comprobantes.",
                    )
                ],
                phase="requirements_sin_comprobantes",
            )
        if "guardia" in text:
            return _valid_decision(
                final_message=(
                    "Como guardia lo revisamos con el plan correspondiente. "
                    "El enganche se deriva por sistema; dime que moto te interesa."
                ),
                fields=[
                    _field(
                        "Plan_Credito",
                        PLAN_GUARDIA,
                        "Cliente dijo que es guardia de seguridad.",
                    )
                ],
                phase="guardia",
            )
        if "adventure" in text:
            return _tool_then_final(
                tool_names=tool_names,
                tool="catalog.search",
                arguments={"query": "adventure"},
                final_message=(
                    "Me salen varias opciones parecidas. Dime cual es la exacta "
                    "para no cotizarte otra moto."
                ),
                phase="modelo_ambiguo",
            )
        if "buro" in text or "buró" in text or "cotiza" in text:
            return _quote_decision(tool_names=tool_names, phase="quote_buro")
        if "cambiar" in text or "mejor la" in text:
            return _quote_decision(
                tool_names=tool_names,
                phase="model_change",
                model="Vento Rocketman",
                message=(
                    "Va, cambio la moto a Vento Rocketman y recotizo conservando "
                    "el plan. Confirmame si esa es la correcta."
                ),
            )
        if "manana mando" in text or "mañana mando" in text:
            return _tool_then_final(
                tool_names=tool_names,
                tool="requirements.lookup",
                arguments={"Plan_Credito": PLAN_NOMINA_TARJETA},
                final_message=(
                    "Va, cuando lo tengas mandalo completo y legible por aqui. "
                    "Mientras dime que moto quieres revisar."
                ),
                phase="future_document_promise",
            )
        if text.strip() in {"?", "??", "que sigue?", "que sigue"}:
            return _valid_decision(
                final_message=(
                    "Seguimos con el dato pendiente: dime que moto te interesa "
                    "para revisarla bien."
                ),
                phase="question_mark_context",
            )
        if "trabajo" in text and "nomina" not in text:
            return _valid_decision(
                final_message=(
                    "Para ubicar tu plan, dime si compruebas ingresos con nomina, "
                    "recibos, negocio, sin comprobantes o guardia."
                ),
                phase="trabajo_ambiguity",
            )
        if "nomina" in text or "nómina" in text or "tarjeta" in text:
            return _valid_decision(
                final_message=(
                    "Va, si te pagan por tarjeta todavia confirmo si tienes recibos "
                    "o solo estado de cuenta. Dime cual aplica."
                ),
                phase="income_pending_slot",
            )
        return _valid_decision(
            final_message=(
                "Claro, para revisar credito primero dime cuanto tiempo llevas "
                "trabajando."
            ),
            phase="new_credit_seniority",
        )


def readiness_scenarios() -> tuple[PhaseAScenario, ...]:
    return (
        PhaseAScenario(
            key="new_credit_seniority",
            name="Cliente nuevo pide credito",
            turns=("Hola quiero sacar una moto a credito",),
            final_message_contains=("cuanto tiempo llevas trabajando",),
        ),
        PhaseAScenario(
            key="no_califica_antiguedad",
            name="Dos meses trabajando no califica",
            turns=("Tengo 2 meses trabajando",),
            expected_fields=("Cumple_Antiguedad",),
            expected_workflows=("pipeline.transition",),
            final_message_contains=("menores a 6 meses",),
        ),
        PhaseAScenario(
            key="income_pending_slot_answer",
            name="Nomina tarjeta pregunta recibos",
            turns=("Me pagan con nomina en tarjeta",),
            final_message_contains=("confirmo si tienes recibos",),
        ),
        PhaseAScenario(
            key="sin_comprobantes_requirements",
            name="Sin comprobantes requisitos",
            turns=("Soy sin comprobantes, que documentos piden?",),
            expected_tools=("requirements.lookup",),
            expected_fields=("Plan_Credito",),
            final_message_contains=("INE", "comprobante de domicilio"),
        ),
        PhaseAScenario(
            key="guardia_no_free_enganche",
            name="Guardia deriva enganche",
            turns=("Soy guardia de seguridad",),
            expected_fields=("Plan_Credito",),
            final_message_contains=("enganche se deriva por sistema",),
        ),
        PhaseAScenario(
            key="ambiguous_model_catalog",
            name="Modelo ambiguo usa catalogo",
            turns=("Me interesa una adventure",),
            expected_tools=("catalog.search",),
            final_message_contains=("varias opciones parecidas",),
        ),
        PhaseAScenario(
            key="quote_model_buro",
            name="Cotizacion con modelo y buro",
            turns=("Cotiza la Vento Xpress con nomina y dime si checan buro",),
            expected_tools=("quote.resolve", "faq.lookup"),
            expected_fields=("Moto", "Plan_Credito"),
            final_message_contains=("cotizacion validada", "buro"),
        ),
        PhaseAScenario(
            key="model_change_quote",
            name="Cambio de moto recotiza",
            turns=("Mejor la Vento Rocketman, puedes cambiarla?",),
            expected_tools=("quote.resolve", "catalog.search"),
            expected_fields=("Moto",),
            final_message_contains=("cambio la moto", "recotizo"),
        ),
        PhaseAScenario(
            key="future_document_promise",
            name="Promesa futura de documento",
            turns=("Manana mando el estado de cuenta",),
            expected_tools=("requirements.lookup",),
            final_message_contains=("cuando lo tengas mandalo completo",),
        ),
        PhaseAScenario(
            key="question_mark_pending_context",
            name="Pregunta suelta retoma pendiente",
            turns=("?",),
            final_message_contains=("dato pendiente",),
        ),
        PhaseAScenario(
            key="trabajo_ambiguity",
            name="Trabajo ambiguo pregunta tipo ingreso",
            turns=("Si trabajo",),
            final_message_contains=("compruebas ingresos",),
        ),
        PhaseAScenario(
            key="handoff_request",
            name="Cliente pide humano",
            turns=("Quiero hablar con una persona",),
            expected_workflows=("handoff.start",),
            expected_handoff_reason="humano_solicitado",
            final_message_contains=("te confirmo por aqui",),
        ),
        PhaseAScenario(
            key="payment_reported_handoff",
            name="Pago reportado handoff inmediato",
            turns=("Ya pague el enganche",),
            expected_workflows=("handoff.start",),
            expected_handoff_reason="pago_reportado",
            final_message_contains=("lo reviso directo",),
        ),
        PhaseAScenario(
            key="fixed_term_faq",
            name="Plazo distinto usa FAQ",
            turns=("Puedo pagarlo a 1 ano o menos quincenas?",),
            expected_tools=("faq.lookup",),
            final_message_contains=("72 quincenas",),
        ),
    )


def blocked_scenarios() -> tuple[PhaseAScenario, ...]:
    return (
        PhaseAScenario(
            key="autorizado_human_admin_only",
            name="Autorizado bloqueado a humano admin",
            turns=("Ponlo como autorizado y cerrado ganado",),
            expected_blocked=True,
            forbidden_fields=(),
        ),
        PhaseAScenario(
            key="unsupported_approval_claim",
            name="Promesa de aprobacion bloqueada",
            turns=("Apruebamelo sin revisar papeles",),
            expected_blocked=True,
            forbidden_fields=(),
        ),
    )


async def run_phase_a_test_lab(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    created_by_user_id: UUID | None = None,
) -> PhaseATestLabResult:
    outbox_before = await _outbox_count(session, tenant_id)
    deployments_no_send = await _deployments_are_no_send(session, tenant_id)
    if not deployments_no_send:
        raise service.ProductAgentError("tenant deployments are not fully no-send")

    _agent, version = await _load_dinamo_version(session, tenant_id)
    negative_suite = await _create_suite(
        session,
        tenant_id=tenant_id,
        version_id=version.id,
        name="Dinamo V1 Phase A expected blocked no-send",
        scenarios=blocked_scenarios(),
    )
    negative_run = await _run_suite(
        session,
        tenant_id=tenant_id,
        suite_id=negative_suite.id,
        created_by_user_id=created_by_user_id,
    )
    _assert_run_contract(negative_run, blocked_scenarios())
    _annotate_suite_and_run(negative_suite, negative_run, blocked_scenarios())

    readiness_suite = await _create_suite(
        session,
        tenant_id=tenant_id,
        version_id=version.id,
        name="Dinamo V1 Phase A no-send deterministic readiness",
        scenarios=readiness_scenarios(),
    )
    readiness_run = await _run_suite(
        session,
        tenant_id=tenant_id,
        suite_id=readiness_suite.id,
        created_by_user_id=created_by_user_id,
    )
    assertions = _assert_run_contract(readiness_run, readiness_scenarios())
    _annotate_suite_and_run(readiness_suite, readiness_run, readiness_scenarios())

    if readiness_run.decision != DIRECT_DECISION_READY:
        raise service.ProductAgentError("readiness direct Test Lab did not pass")

    outbox_after = await _outbox_count(session, tenant_id)
    return PhaseATestLabResult(
        tenant_id=str(tenant_id),
        negative_suite_id=str(negative_suite.id),
        negative_run_id=str(negative_run.id),
        readiness_suite_id=str(readiness_suite.id),
        readiness_run_id=str(readiness_run.id),
        readiness_status=readiness_run.status,
        readiness_decision=readiness_run.decision,
        readiness_pass_count=readiness_run.pass_count,
        readiness_blocked_count=readiness_run.blocked_count,
        outbox_before=outbox_before,
        outbox_after=outbox_after,
        outbox_delta=outbox_after - outbox_before,
        deployments_no_send=deployments_no_send,
        assertions=assertions,
    )


async def _load_dinamo_version(
    session: AsyncSession,
    tenant_id: UUID,
) -> tuple[Agent, AgentVersion]:
    agent = (
        await session.execute(
            select(Agent).where(Agent.tenant_id == tenant_id, Agent.name == AGENT_NAME)
        )
    ).scalars().one_or_none()
    if agent is None:
        raise service.ProductAgentNotFoundError("Dinamo seeded agent was not found")
    version = (
        await session.execute(
            select(AgentVersion)
            .where(AgentVersion.tenant_id == tenant_id, AgentVersion.agent_id == agent.id)
            .order_by(AgentVersion.version_number.desc())
        )
    ).scalars().first()
    if version is None:
        raise service.ProductAgentNotFoundError("Dinamo seeded agent version was not found")
    return agent, version


async def _create_suite(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    version_id: UUID,
    name: str,
    scenarios: tuple[PhaseAScenario, ...],
):
    timestamp = datetime.now(UTC).isoformat()
    suite = await service.create_agent_test_suite(
        session,
        tenant_id=tenant_id,
        version_id=version_id,
        name=f"{name} - {timestamp}",
        mode="draft_validation",
        metadata={
            "source": "dinamo_phase_a_no_send_test_lab",
            "seed_id": SEED_ID,
            "openai_api_real": False,
            "external_apis": False,
            "send": "no_send",
            "scenario_keys": [scenario.key for scenario in scenarios],
        },
    )
    for scenario in scenarios:
        await service.create_agent_test_scenario(
            session,
            tenant_id=tenant_id,
            suite_id=suite.id,
            name=scenario.name,
            turns=[{"inbound_text": turn} for turn in scenario.turns],
            expected=scenario.as_expected(),
            metadata={
                "scenario_key": scenario.key,
                "source": "dinamo_phase_a_no_send_test_lab",
                "openai_api_real": False,
                "external_apis": False,
            },
        )
    return suite


async def _run_suite(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    suite_id: UUID,
    created_by_user_id: UUID | None,
) -> AgentTestRun:
    return await test_lab_direct_adapter.run_direct_test_suite(
        session,
        tenant_id=tenant_id,
        suite_id=suite_id,
        created_by_user_id=created_by_user_id,
        tool_loop_factory=_tool_loop_factory,
        max_tool_rounds=3,
    )


def _tool_loop_factory(config) -> RespondStyleToolLoop:
    return RespondStyleToolLoop(
        provider=DeterministicDinamoPhaseAProvider(),
        executor=DryFactsToolExecutor(config.tool_bindings),
        config=RespondStyleToolLoopConfig(max_tool_rounds=3, max_total_tool_calls=8),
    )


def _assert_run_contract(
    run: AgentTestRun,
    scenarios: tuple[PhaseAScenario, ...],
) -> list[str]:
    failures: list[str] = []
    turn_results = list(run.turn_results or [])
    if len(turn_results) != len(scenarios):
        failures.append("turn_result_count_mismatch")
    for scenario, turn in zip(scenarios, turn_results, strict=False):
        failures.extend(_assert_turn_contract(scenario, turn))

    if any(scenario.expected_blocked for scenario in scenarios):
        if run.decision != DIRECT_DECISION_BLOCKED:
            failures.append("expected_blocked_run_not_blocked")
    elif run.decision != DIRECT_DECISION_READY:
        failures.append("readiness_run_not_ready")

    if failures:
        run.status = "failed"
        run.decision = DIRECT_DECISION_BLOCKED
        run.fail_count = len(failures)
        run.coverage_summary = {
            **(run.coverage_summary or {}),
            "assertion_failures": failures,
        }
        raise service.ProductAgentError(
            "Dinamo Phase A no-send Test Lab assertions failed: "
            + ", ".join(failures)
        )
    return ["passed"]


def _assert_turn_contract(scenario: PhaseAScenario, turn: JsonDict) -> list[str]:
    failures: list[str] = []
    blocked_reason = turn.get("blocked_reason")
    if scenario.expected_blocked:
        if blocked_reason is None:
            failures.append(f"{scenario.key}:expected_blocked")
        return failures
    if blocked_reason is not None:
        failures.append(f"{scenario.key}:unexpected_blocked:{blocked_reason}")
    tools = {
        item.get("tool_name")
        for item in turn.get("tools") or []
        if item.get("status") == "succeeded"
    }
    for tool in scenario.expected_tools:
        if tool not in tools:
            failures.append(f"{scenario.key}:missing_tool:{tool}")
    fields = {
        item.get("field_key") for item in turn.get("field_update_proposals") or []
    }
    for field_key in scenario.expected_fields:
        if field_key not in fields:
            failures.append(f"{scenario.key}:missing_field:{field_key}")
    for field_key in scenario.forbidden_fields:
        if field_key in fields:
            failures.append(f"{scenario.key}:forbidden_field:{field_key}")
    workflows = {
        item.get("binding_name") for item in turn.get("workflow_event_proposals") or []
    }
    for workflow in scenario.expected_workflows:
        if workflow not in workflows:
            failures.append(f"{scenario.key}:missing_workflow:{workflow}")
    handoff = turn.get("handoff_proposal") or {}
    if scenario.expected_handoff_reason:
        if handoff.get("reason") != scenario.expected_handoff_reason:
            failures.append(f"{scenario.key}:handoff_reason_mismatch")
    final_message = str(turn.get("final_message") or "")
    for expected in scenario.final_message_contains:
        if _fold(expected) not in _fold(final_message):
            failures.append(f"{scenario.key}:final_message_missing:{expected}")
    for forbidden in scenario.forbidden_final_message_contains:
        if _fold(forbidden) in _fold(final_message):
            failures.append(f"{scenario.key}:final_message_forbidden:{forbidden}")
    return failures


def _annotate_suite_and_run(
    suite,
    run: AgentTestRun,
    scenarios: tuple[PhaseAScenario, ...],
) -> None:
    suite.last_run_id = run.id
    suite.status = "passed" if run.decision == DIRECT_DECISION_READY else "blocked"
    run.coverage_summary = {
        **(run.coverage_summary or {}),
        "source": "dinamo_phase_a_no_send_test_lab",
        "scenario_keys": [scenario.key for scenario in scenarios],
        "openai_api_real": False,
        "external_apis": False,
        "assertions": "passed",
    }


async def _outbox_count(session: AsyncSession, tenant_id: UUID) -> int:
    count = await session.scalar(
        select(func.count())
        .select_from(OutboundOutbox)
        .where(OutboundOutbox.tenant_id == tenant_id)
    )
    return int(count or 0)


async def _deployments_are_no_send(session: AsyncSession, tenant_id: UUID) -> bool:
    deployments = (
        await session.execute(
            select(AgentDeployment).where(AgentDeployment.tenant_id == tenant_id)
        )
    ).scalars().all()
    return bool(deployments) and all(
        not deployment.send_enabled
        and not deployment.outbox_enabled
        and not deployment.live_send_enabled
        and not deployment.single_contact_smoke_enabled
        and not deployment.actions_enabled
        and not deployment.workflow_events_enabled
        and not deployment.workflow_side_effects_enabled
        and not deployment.canary_enabled
        and not deployment.open_production_enabled
        and deployment.send_scope == "none"
        and deployment.runtime_mode == "no_send"
        for deployment in deployments
    )


def _quote_decision(
    *,
    tool_names: set[str],
    phase: str,
    model: str = "Vento Xpress",
    message: str | None = None,
) -> FinalTurnDecision:
    required_tools = {"quote.resolve", "faq.lookup"} if phase == "quote_buro" else {
        "quote.resolve",
        "catalog.search",
    }
    missing = [tool for tool in sorted(required_tools) if tool not in tool_names]
    if missing:
        return _valid_decision(
            tools=[
                _tool(
                    tool,
                    {"Moto": model, "Plan_Credito": PLAN_NOMINA_TARJETA},
                    f"Need {tool} dry facts.",
                )
                for tool in missing
            ],
            fields=[
                _field("Moto", model, f"Cliente pidio {model}."),
                _field(
                    "Plan_Credito",
                    PLAN_NOMINA_TARJETA,
                    "Cliente menciono nomina o cotizacion por plan de nomina.",
                ),
            ],
            phase=phase,
        )
    return _valid_decision(
        final_message=message
        or (
            "Ya tengo la cotizacion validada para esa moto y plan. Tambien se "
            "revisa buro; para avanzar dime si tienes al menos 6 meses trabajando."
        ),
        fields=[
            _field("Moto", model, f"Cliente pidio {model}."),
            _field(
                "Plan_Credito",
                PLAN_NOMINA_TARJETA,
                "Cliente menciono nomina o cotizacion por plan de nomina.",
            ),
        ],
        phase=phase,
    )


def _tool_then_final(
    *,
    tool_names: set[str],
    tool: str,
    arguments: JsonDict,
    final_message: str,
    phase: str,
    fields: list[LLMFieldUpdateProposal] | None = None,
) -> FinalTurnDecision:
    if tool not in tool_names:
        return _valid_decision(
            tools=[_tool(tool, arguments, f"Need {tool} dry facts.")],
            fields=fields or [],
            phase=phase,
        )
    return _valid_decision(
        final_message=final_message,
        fields=fields or [],
        phase=phase,
    )


def _valid_decision(
    *,
    final_message: str | None = None,
    tools: list[LLMToolCallProposal] | None = None,
    fields: list[LLMFieldUpdateProposal] | None = None,
    workflows: list[LLMWorkflowEventProposal] | None = None,
    handoff: LLMHandoffProposal | None = None,
    phase: str,
) -> FinalTurnDecision:
    return FinalTurnDecision(
        final_message=final_message,
        validation=AgentTurnValidationResult(
            status="valid",
            accepted_tool_requests=tools or [],
            accepted_field_writes=fields or [],
            accepted_workflow_events=workflows or [],
            send_decision="no_send",
        ),
        accepted_field_writes=fields or [],
        accepted_workflow_events=workflows or [],
        accepted_handoff=handoff,
        trace_metadata={
            "provider": "deterministic_dinamo_phase_a_no_openai",
            "phase": phase,
            "openai_api_real": False,
        },
    )


def _handoff_decision(*, reason: str, message: str) -> FinalTurnDecision:
    return _valid_decision(
        final_message=message,
        workflows=[
            _workflow(
                "handoff.start",
                "human_handoff_requested",
                {"Motivo_Handoff": reason},
            )
        ],
        handoff=LLMHandoffProposal(
            needed=True,
            reason=reason,
            target="Francisco Esparza",
            priority="normal",
        ),
        phase=f"handoff:{reason}",
    )


def _blocked_decision(reason: str) -> FinalTurnDecision:
    return FinalTurnDecision(
        validation=AgentTurnValidationResult(
            status="blocked",
            blocked_reason=reason,
            blocked_items=[
                ValidationErrorItem(
                    code=reason,
                    message="Expected fail-closed no-send guard.",
                )
            ],
            send_decision="no_send",
        ),
        trace_metadata={
            "provider": "deterministic_dinamo_phase_a_no_openai",
            "phase": "expected_blocked",
            "openai_api_real": False,
        },
    )


def _tool(tool_name: str, arguments: JsonDict, reason: str) -> LLMToolCallProposal:
    return LLMToolCallProposal(
        tool_name=tool_name,
        arguments=arguments,
        reason=reason,
        required=True,
    )


def _field(field_key: str, value: Any, evidence: str) -> LLMFieldUpdateProposal:
    return LLMFieldUpdateProposal(
        field_key=field_key,
        value=value,
        evidence=[evidence],
        confidence=0.9,
        reason=evidence,
    )


def _workflow(
    binding_name: str,
    event_name: str,
    payload: JsonDict,
) -> LLMWorkflowEventProposal:
    return LLMWorkflowEventProposal(
        binding_name=binding_name,
        event_name=event_name,
        payload=payload,
        reason=f"Propose {binding_name} in no-send dry-run.",
    )


def _tool_names(context: AgentContextPackage) -> set[str]:
    return {
        str(item.get("tool_name"))
        for item in context.tool_results
        if isinstance(item, dict) and item.get("status") == "succeeded"
    }


def _fold(value: str) -> str:
    return value.casefold().strip()


async def _main(tenant_id: UUID) -> int:
    async for session in get_db_session():
        try:
            result = await run_phase_a_test_lab(session, tenant_id=tenant_id)
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        print(json.dumps(result.as_dict(), indent=2, sort_keys=True))
        return 0
    return 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant-id", type=UUID, required=True)
    args = parser.parse_args()
    return asyncio.run(_main(args.tenant_id))


if __name__ == "__main__":
    sys.exit(main())
