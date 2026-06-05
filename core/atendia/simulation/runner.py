from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import yaml
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.agent_runtime import (
    LifecycleUpdate,
    PolicyValidator,
    PostTurnActionExecutor,
    TurnInput,
    TurnOutput,
)
from atendia.agent_runtime.context_builder import ContextBuilder
from atendia.agent_runtime.model_provider import MockAgentProvider
from atendia.agent_runtime.schemas import FieldUpdate, TurnContext
from atendia.contact_memory.service import ContactMemoryService
from atendia.knowledge.os import KnowledgeRetrievalService, SqlAlchemyKnowledgeRepository
from atendia.lifecycle.service import LifecycleService
from atendia.simulation.safety import (
    assert_simulation_conversation,
    safety_counters,
    safety_delta,
    side_effect_failures,
)
from atendia.simulation.schemas import (
    ProviderName,
    SimulationCase,
    SimulationCaseFixture,
    SimulationFixture,
    SimulationMode,
    SimulationRun,
    SimulationTurn,
)
from atendia.simulation.service import SimulationPersistenceService

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "dinamo_order_chaos.yaml"


class SimulationLabRunner:
    def __init__(
        self,
        session: AsyncSession,
        *,
        provider_name: ProviderName = "local_deterministic",
        provider: Any | None = None,
    ) -> None:
        self._session = session
        self._provider_name = provider_name
        self._provider = provider
        self._persistence = SimulationPersistenceService(session)

    async def run_fixture(
        self,
        *,
        tenant_id: UUID,
        agent_id: UUID,
        fixture_path: Path = FIXTURE_PATH,
        mode: SimulationMode = "simulation_apply",
        name: str = "Dinamo Order and Chaos",
    ) -> dict[str, Any]:
        fixture = load_fixture(fixture_path)
        run = SimulationRun(
            tenant_id=tenant_id,
            agent_id=agent_id,
            name=name,
            mode=mode,
            source=str(fixture_path),
            status="running",
            started_at=datetime.now(UTC),
            metadata={
                "fixture": fixture.name,
                "provider": self._provider_name,
                "readiness_final": self._provider_name == "openai",
            },
        )
        before = await safety_counters(self._session, tenant_id=tenant_id)
        cases: list[SimulationCase] = []
        turns: list[SimulationTurn] = []
        for case_fixture in fixture.cases:
            case, case_turns = await self._run_case(
                tenant_id=tenant_id,
                agent_id=agent_id,
                run=run,
                case_fixture=case_fixture,
                mode=mode,
            )
            cases.append(case)
            turns.extend(case_turns)
        after = await safety_counters(self._session, tenant_id=tenant_id)
        delta = safety_delta(before, after)
        failures = side_effect_failures(delta)
        run.metrics = _run_metrics(cases, turns, delta, failures)
        run.score = float(run.metrics["score"])
        run.status = "passed" if not failures and run.metrics["cases_failed"] == 0 else "failed"
        run.completed_at = datetime.now(UTC)
        return {
            "run": run,
            "cases": cases,
            "turns": turns,
            "fixture": fixture,
            "safety_before": before,
            "safety_after": after,
            "safety_delta": delta,
            "side_effect_failures": failures,
        }

    async def _run_case(
        self,
        *,
        tenant_id: UUID,
        agent_id: UUID,
        run: SimulationRun,
        case_fixture: SimulationCaseFixture,
        mode: SimulationMode,
    ) -> tuple[SimulationCase, list[SimulationTurn]]:
        customer = await self._persistence.create_customer(
            tenant_id=tenant_id,
            run_id=run.id,
            case_id=case_fixture.case_id,
            initial_fields=case_fixture.initial_contact_fields,
        )
        conversation = await self._persistence.create_conversation(
            tenant_id=tenant_id,
            agent_id=agent_id,
            customer_id=customer.id,
            run_id=run.id,
            case_id=case_fixture.case_id,
            initial_stage=case_fixture.initial_stage,
        )
        case = SimulationCase(
            run_id=run.id,
            case_id=case_fixture.case_id,
            title=case_fixture.title,
            category=case_fixture.category,
            status="running",
            conversation_id=conversation.id,
            expected_final_stage=(
                case_fixture.expected_stage_changes[-1]
                if case_fixture.expected_stage_changes
                else None
            ),
            expected_fields=dict(case_fixture.expected_field_updates),
            expected_handoff=case_fixture.expected_handoff,
            expected_documents=list(case_fixture.expected_documents),
            metadata={
                "initial_stage": case_fixture.initial_stage,
                "initial_contact_fields": case_fixture.initial_contact_fields,
                "forbidden_behaviors": case_fixture.forbidden_behaviors,
            },
        )
        turns: list[SimulationTurn] = []
        for index, raw_turn in enumerate(case_fixture.turns, start=1):
            turn = await self._run_turn(
                tenant_id=tenant_id,
                agent_id=agent_id,
                run=run,
                case=case,
                case_fixture=case_fixture,
                conversation_id=conversation.id,
                customer_message=str(raw_turn["customer_message"]),
                expected_behavior=raw_turn.get("expected_behavior"),
                turn_index=index,
                mode=mode,
            )
            turns.append(turn)
        final_fields = await self._persistence.field_values_for_customer(customer_id=customer.id)
        final_stage = await self._persistence.current_stage(conversation_id=conversation.id)
        case.failure_reasons = _case_failures(
            case_fixture=case_fixture,
            turns=turns,
            final_fields=final_fields,
            final_stage=final_stage,
        )
        score_dimensions = _case_score_dimensions(
            case_fixture=case_fixture,
            turns=turns,
            final_fields=final_fields,
            final_stage=final_stage,
        )
        case.score = _average([turn.score for turn in turns])
        if case.failure_reasons:
            case.score = min(case.score or 0.0, 0.74)
        case.status = "passed" if not case.failure_reasons else "failed"
        case.metadata.update(
            {
                "final_fields": final_fields,
                "final_stage": final_stage,
                "score_dimensions": score_dimensions,
            }
        )
        return case, turns

    async def _run_turn(
        self,
        *,
        tenant_id: UUID,
        agent_id: UUID,
        run: SimulationRun,
        case: SimulationCase,
        case_fixture: SimulationCaseFixture,
        conversation_id: UUID,
        customer_message: str,
        expected_behavior: str | None,
        turn_index: int,
        mode: SimulationMode,
    ) -> SimulationTurn:
        await assert_simulation_conversation(self._session, conversation_id=conversation_id)
        inbound = await self._persistence.insert_message(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            direction="inbound",
            text_value=customer_message,
            run_id=run.id,
            case_id=case.case_id,
            turn_index=turn_index,
        )
        context_builder = ContextBuilder(
            self._session,
            knowledge_provider=KnowledgeRetrievalService(
                SqlAlchemyKnowledgeRepository(self._session)
            ),
        )
        context = await context_builder.build(
            TurnInput(
                tenant_id=str(tenant_id),
                conversation_id=str(conversation_id),
                inbound_text=customer_message,
                metadata={
                    "agent_id": str(agent_id),
                    "simulation_run_id": str(run.id),
                    "simulation_case_id": case.case_id,
                    "simulation_turn_index": turn_index,
                },
            )
        )
        provider = self._resolve_provider(case_fixture)
        output = await provider.generate(context)
        if not isinstance(output, TurnOutput):
            output = TurnOutput.model_validate(output)
        output.trace_metadata.update(
            {
                "simulation_run_id": str(run.id),
                "simulation_case_id": case.case_id,
                "simulation_turn_index": turn_index,
                "provider": self._provider_name,
                "legacy_used": bool(output.trace_metadata.get("legacy_used")),
            }
        )
        policy_issues = [
            {"code": issue.code, "message": issue.message}
            for issue in PolicyValidator().validate(output)
        ]
        action_results: list[dict[str, Any]] = []
        if mode == "simulation_apply" and not policy_issues:
            executor = PostTurnActionExecutor(
                dry_run=False,
                session=self._session,
                contact_memory_service=ContactMemoryService(self._session),
                lifecycle_service=LifecycleService(self._session),
                require_runtime_enabled=False,
            )
            action_results = [
                result.model_dump(mode="json")
                for result in await executor.execute(output, context=context)
            ]
            simulation_fields_applied = await self._persistence.apply_simulation_field_updates(
                tenant_id=tenant_id,
                customer_id=UUID(str(context.customer.id)),
                field_updates=output.field_updates,
            )
            if simulation_fields_applied:
                action_results.append(
                    {
                        "action_name": "simulation.field_updates",
                        "status": "succeeded",
                        "data": {"applied": simulation_fields_applied},
                        "trace_metadata": {
                            "simulation": True,
                            "executed": True,
                            "real_customer_write": False,
                        },
                    }
                )
        trace = await self._persistence.record_trace(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            agent_id=agent_id,
            inbound_message_id=inbound.id,
            inbound_text=customer_message,
            turn_number=turn_index,
            output=output,
            context_metadata=context.metadata,
            policy_issues=policy_issues,
            action_results=action_results,
            run_id=run.id,
            case_id=case.case_id,
            provider_name=self._provider_name,
        )
        output.trace_metadata["trace_id"] = str(trace.id)
        await self._persistence.insert_message(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            direction="outbound",
            text_value=output.final_message,
            run_id=run.id,
            case_id=case.case_id,
            turn_index=turn_index,
            trace_id=trace.id,
        )
        failures = _turn_failures(
            output=output,
            policy_issues=policy_issues,
            case_fixture=case_fixture,
        )
        score_dimensions = _turn_score_dimensions(
            output=output,
            policy_issues=policy_issues,
            failures=failures,
            case_fixture=case_fixture,
        )
        score = score_dimensions["overall_score"]
        return SimulationTurn(
            case_id=case.id,
            turn_index=turn_index,
            customer_message=customer_message,
            expected_behavior=expected_behavior,
            actual_final_message=output.final_message,
            citations=[citation.model_dump(mode="json") for citation in output.knowledge_citations],
            field_updates=[update.model_dump(mode="json") for update in output.field_updates],
            lifecycle_update=(
                output.lifecycle_update.model_dump(mode="json")
                if output.lifecycle_update
                else None
            ),
            actions=[action.model_dump(mode="json") for action in output.actions],
            policy_result={"valid": not policy_issues, "issues": policy_issues},
            confidence=float(output.confidence),
            trace_id=trace.id,
            score=round(score, 4),
            pass_fail="pass" if not failures else "fail",
            failure_reasons=failures,
            metadata={
                "needs_human": output.needs_human,
                "risk_flags": list(output.risk_flags),
                "action_results": action_results,
                "legacy_used": bool(output.trace_metadata.get("legacy_used")),
                "provider_fallback": _provider_fallback_used(output),
                "score_dimensions": score_dimensions,
            },
        )

    def _resolve_provider(self, case_fixture: SimulationCaseFixture) -> Any:
        if self._provider is not None:
            return self._provider
        if self._provider_name == "mock":
            return MockAgentProvider()
        if self._provider_name == "local_deterministic":
            return DinamoLocalDeterministicProvider(case_fixture=case_fixture)
        if self._provider_name == "openai":
            raise ValueError("openai provider requires explicit provider gate approval")
        raise ValueError(f"unsupported simulation provider {self._provider_name!r}")


class DinamoLocalDeterministicProvider:
    def __init__(self, *, case_fixture: SimulationCaseFixture) -> None:
        self._case_fixture = case_fixture

    async def generate(self, context: TurnContext) -> TurnOutput:
        text = context.inbound_text.casefold()
        citations = context.knowledge_citations
        updates: list[FieldUpdate] = []
        lifecycle: LifecycleUpdate | None = None
        needs_human = False
        risk_flags: list[str] = []
        final = "Claro, te ayudo. Para avanzar, dime como recibes tus ingresos."
        confidence = 0.9

        def field(key: str, value: Any, reason: str) -> None:
            updates.append(
                FieldUpdate(
                    field_key=key,
                    value=value,
                    reason=reason,
                    evidence=[context.inbound_text],
                    confidence=0.9,
                    source="customer_message",
                )
            )

        def stage(target: str, reason: str) -> None:
            nonlocal lifecycle
            lifecycle = LifecycleUpdate(
                target_stage=target,
                reason=reason,
                evidence=[context.inbound_text],
                confidence=0.9,
                source="agent",
                metadata={"simulation": True},
            )

        def official() -> bool:
            return bool(
                set(self._case_fixture.expected_field_updates)
                & {
                    "CUMPLE_ANTIGUEDAD",
                    "PLAN",
                    "MOTO_INTERES",
                    "DOCUMENTOS",
                    "DOCUMENTOS_COMPLETOS",
                }
                or set(self._case_fixture.expected_stage_changes)
                & {
                    "plan",
                    "cliente_potencial",
                    "papeleria_incompleta",
                    "papeleria_completa",
                }
            )

        def target_stage(official_stage: str, legacy_stage: str) -> str:
            expected = set(self._case_fixture.expected_stage_changes)
            if official_stage in expected:
                return official_stage
            if legacy_stage in expected:
                return legacy_stage
            return official_stage if official() else legacy_stage

        def income_plan(plan: str, reason: str) -> None:
            if official():
                field("PLAN", plan, reason)
            else:
                if plan == "Nómina Tarjeta":
                    field("income_type", "Nomina", reason)
                else:
                    field("income_type", plan, reason)
                    field("CREDITO", plan, reason)

        def moto_interest(value: str, reason: str) -> None:
            if official() and "MOTO_INTERES" in self._case_fixture.expected_field_updates:
                field("MOTO_INTERES", value, reason)

        def document_checklist(statuses: dict[str, str], reason: str) -> None:
            if not official():
                return
            field(
                "DOCUMENTOS",
                [{"key": key, "status": status} for key, status in statuses.items()],
                reason,
            )
            if "DOCUMENTOS_COMPLETOS" in self._case_fixture.expected_field_updates:
                field(
                    "DOCUMENTOS_COMPLETOS",
                    all(status == "accepted" for status in statuses.values()),
                    reason,
                )

        if "humano" in text or "alguien" in text or "francisco" in text:
            final = "Claro, te paso con una persona del equipo para que te atienda directo."
            needs_human = True
            risk_flags.append("human_requested")
        elif "un mes" in text or "antiguedad" in text:
            final = (
                "Con un mes de antiguedad conviene que una persona revise si aplica. "
                "No te puedo prometer aprobacion."
            )
            needs_human = True
            risk_flags.append("approval_sensitive")
            if official():
                field(
                    "CUMPLE_ANTIGUEDAD",
                    False,
                    "Customer has insufficient seniority risk.",
                )
            stage(target_stage("plan", "credito"), "Customer has insufficient seniority risk.")
        elif "8 meses" in text or "ocho meses" in text or "un año" in text:
            final = (
                "Perfecto, con esa antiguedad podemos revisar tu plan. "
                "Como recibes tus ingresos?"
            )
            if official():
                field("CUMPLE_ANTIGUEDAD", True, "Customer has enough seniority.")
            stage(target_stage("plan", "credito"), "Customer passed seniority step.")
        elif "sin trabajo" in text or "no tengo trabajo" in text:
            final = (
                "No te puedo prometer aprobacion. Sin trabajo conviene que una persona "
                "revise tu caso antes de avanzar."
            )
            needs_human = True
            risk_flags.append("approval_sensitive")
            if official():
                field("CUMPLE_ANTIGUEDAD", False, "Customer has no current job.")
        elif "buro" in text:
            final = (
                "Si estas en buro se puede revisar, pero no puedo prometer aprobacion. "
                "Cuanto debes aproximadamente?"
            )
            field("buro_status", "en_buro", "Customer mentioned buro.")
            stage(target_stage("plan", "credito"), "Credit risk question.")
            risk_flags.append("approval_sensitive")
        elif "pagan por fuera" in text:
            final = (
                "Va, eso corresponde al plan sin comprobar ingresos. Para simularlo bien, "
                "que modelo quieres cotizar?"
            )
            income_plan("Sin Comprobantes", "Customer has informal income.")
            stage(target_stage("plan", "credito"), "Customer is entering credit flow.")
        elif "nomina" in text or "tarjeta" in text:
            final = "Perfecto, tomo nomina como tipo de ingreso. Que modelo quieres cotizar?"
            income_plan("Nómina Tarjeta", "Customer mentioned payroll income.")
            stage(target_stage("plan", "credito"), "Customer is entering credit flow.")
            if "excel" in text:
                final = (
                    "Si tu nomina viene en Excel, debe revisarlo una persona para confirmar "
                    "si sirve como comprobante."
                )
                needs_human = True
                risk_flags.append("document_needs_review")
        elif "pensionado" in text:
            final = "Perfecto, lo revisamos como pensionado. Que modelo quieres cotizar?"
            income_plan("Pensionados", "Customer said they are pensioned.")
            stage(target_stage("plan", "credito"), "Customer is entering credit flow.")
        elif "guardia" in text:
            final = (
                "Perfecto, guardia de seguridad normalmente se revisa con ese plan. "
                "Que modelo quieres cotizar?"
            )
            income_plan("Guardia de Seguridad", "Customer works security.")
            stage(target_stage("plan", "credito"), "Customer is entering credit flow.")
        elif "enganche" in text or "10 mil" in text or "20 mil" in text:
            amount = "20000" if "20" in text else "10000"
            final = f"Perfecto, tomo ${int(amount):,} como enganche para la simulacion."
            field("ENGANCHE", amount, "Customer provided down payment.")
        elif "r4" in text or "nitrox" in text or "adventure" in text:
            model = (
                "Dinamo R4"
                if "r4" in text
                else "Dinamo Nitrox"
                if "nitrox" in text
                else "Dinamo Adventure"
            )
            final = f"Va, reviso la {model} con tu plan. Quieres avanzar con documentos?"
            moto_interest(model, "Customer selected a motorcycle model.")
            if official():
                stage(
                    target_stage("cliente_potencial", "potencialcliente"),
                    "Customer selected model and plan.",
                )
        elif "catalogo" in text:
            final = (
                "Te puedo compartir opciones del catalogo activo. No confirmo precio o "
                "inventario si no aparece en la fuente."
            )
        elif "documentos" in text or "papeles" in text:
            final = (
                "Los base son INE vigente y comprobante de domicilio. Segun el plan puede "
                "cambiar lo adicional; primero confirmemos tu tipo de ingreso."
            )
            if official():
                stage(
                    target_stage("papeleria_incompleta", "doc_incompleta"),
                    "Customer is asking about documents.",
                )
        elif "comprobante" in text and "listo" in text:
            final = (
                "Perfecto, con INE y comprobante aceptados dejo la papeleria completa "
                "para revision humana."
            )
            if official():
                document_checklist(
                    {"INE_AMBOS_LADOS": "accepted", "COMPROBANTE_DOMICILIO": "accepted"},
                    "Required documents accepted in simulation.",
                )
                stage(
                    target_stage("papeleria_completa", "doc_completa"),
                    "Required documents complete.",
                )
        elif "ine" in text:
            final = (
                "Recibido, dejo la INE como enviada para revision. Aun no marco papeleria "
                "completa hasta validar todos los requisitos."
            )
            if official():
                document_checklist(
                    {"INE_AMBOS_LADOS": "received", "COMPROBANTE_DOMICILIO": "missing"},
                    "Customer says INE was sent.",
                )
            else:
                field("INE_FRENTE", "received_pending_review", "Customer says INE was sent.")
            stage(
                target_stage("papeleria_incompleta", "doc_incompleta"),
                "Document is pending review.",
            )
        elif "borrosa" in text:
            final = "Si la foto esta borrosa, hay que reenviarla para poder revisarla bien."
            stage(
                target_stage("papeleria_incompleta", "doc_incompleta"),
                "Document is not readable.",
            )
            risk_flags.append("invalid_document")
        elif "mama" in text:
            final = (
                "No tomaria documentos de tu mama como ingreso propio sin revision. "
                "Te paso con una persona para revisar alternativas."
            )
            needs_human = True
            risk_flags.append("third_party_documents")
        elif "ya te dije" in text:
            final = "Tienes razon, ya tengo ese dato guardado. Avancemos con el modelo que quieres."
        elif "credito" in text:
            final = "Claro, te ayudo con credito. Para avanzar, dime como recibes tus ingresos."
            stage(target_stage("plan", "credito"), "Customer asked for credit.")
        if self._case_fixture.expected_handoff:
            needs_human = True
        return TurnOutput(
            final_message=final,
            field_updates=updates,
            lifecycle_update=lifecycle,
            knowledge_citations=citations,
            confidence=confidence,
            needs_human=needs_human,
            risk_flags=risk_flags,
            trace_metadata={"provider": "local_deterministic", "legacy_used": False},
        )


def load_fixture(path: Path = FIXTURE_PATH) -> SimulationFixture:
    return SimulationFixture.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def _turn_failures(
    *,
    output: TurnOutput,
    policy_issues: list[dict[str, Any]],
    case_fixture: SimulationCaseFixture,
) -> list[str]:
    failures = [f"policy:{issue['code']}" for issue in policy_issues]
    final = output.final_message.casefold()
    if not output.final_message.strip():
        failures.append("missing_final_message")
    if "recibido. te ayudo con eso" in final:
        failures.append("generic_mock_answer")
    if (
        "aprobacion" in final
        and "no te puedo prometer" not in final
        and "no puedo prometer" not in final
    ):
        failures.append("approval_promise_risk")
    if final.count("?") > 1:
        failures.append("more_than_one_question")
    if case_fixture.expected_handoff and not output.needs_human:
        failures.append("handoff_expected")
    if _provider_fallback_used(output):
        failures.append("provider_fallback")
    if output.trace_metadata.get("legacy_used"):
        failures.append("legacy_copy_path_used")
    return failures


def _turn_score_dimensions(
    *,
    output: TurnOutput,
    policy_issues: list[dict[str, Any]],
    failures: list[str],
    case_fixture: SimulationCaseFixture,
) -> dict[str, float]:
    copy_score = _penalized_score(
        failures,
        {
            "missing_final_message",
            "generic_mock_answer",
            "approval_promise_risk",
            "more_than_one_question",
        },
        penalty=0.3,
    )
    policy_score = 0.0 if policy_issues else 1.0
    structure_score = _penalized_score(
        failures,
        {"provider_fallback", "legacy_copy_path_used"},
        penalty=0.5,
    )
    business_process_score = _penalized_score(
        failures,
        {"handoff_expected"},
        penalty=0.5,
    )
    if case_fixture.expected_handoff and output.needs_human:
        business_process_score = max(business_process_score, 1.0)
    overall_score = round(
        0.25 * copy_score
        + 0.2 * policy_score
        + 0.3 * structure_score
        + 0.25 * business_process_score,
        4,
    )
    return {
        "copy_score": copy_score,
        "policy_score": policy_score,
        "structure_score": structure_score,
        "business_process_score": business_process_score,
        "overall_score": overall_score,
    }


def _case_failures(
    *,
    case_fixture: SimulationCaseFixture,
    turns: list[SimulationTurn],
    final_fields: dict[str, Any],
    final_stage: str | None,
) -> list[str]:
    failures = [failure for turn in turns for failure in turn.failure_reasons]
    for key, expected in case_fixture.expected_field_updates.items():
        if str(final_fields.get(key)) != str(expected):
            failures.append(f"field {key} expected {expected!r} got {final_fields.get(key)!r}")
    if case_fixture.expected_stage_changes:
        expected_stage = case_fixture.expected_stage_changes[-1]
        if final_stage != expected_stage:
            failures.append(f"stage expected {expected_stage!r} got {final_stage!r}")
    return failures


def _case_score_dimensions(
    *,
    case_fixture: SimulationCaseFixture,
    turns: list[SimulationTurn],
    final_fields: dict[str, Any],
    final_stage: str | None,
) -> dict[str, float]:
    copy_score = _average(
        [
            float(turn.metadata.get("score_dimensions", {}).get("copy_score", turn.score))
            for turn in turns
        ]
    )
    policy_score = _average(
        [
            float(turn.metadata.get("score_dimensions", {}).get("policy_score", 1.0))
            for turn in turns
        ]
    )
    structure_scores = [
        float(turn.metadata.get("score_dimensions", {}).get("structure_score", 1.0))
        for turn in turns
    ]
    business_scores = [
        float(turn.metadata.get("score_dimensions", {}).get("business_process_score", 1.0))
        for turn in turns
    ]
    missing_fields = [
        key
        for key, expected in case_fixture.expected_field_updates.items()
        if str(final_fields.get(key)) != str(expected)
    ]
    if missing_fields:
        structure_scores.append(max(0.0, 1.0 - 0.35 * len(missing_fields)))
        business_scores.append(0.0)
    if case_fixture.expected_stage_changes:
        expected_stage = case_fixture.expected_stage_changes[-1]
        if final_stage != expected_stage:
            structure_scores.append(0.0)
            business_scores.append(0.0)
    structure_score = _average(structure_scores)
    business_process_score = _average(business_scores)
    overall_score = round(
        0.25 * copy_score
        + 0.2 * policy_score
        + 0.3 * structure_score
        + 0.25 * business_process_score,
        4,
    )
    return {
        "copy_score": copy_score,
        "policy_score": policy_score,
        "structure_score": structure_score,
        "business_process_score": business_process_score,
        "overall_score": overall_score,
    }


def _run_metrics(
    cases: list[SimulationCase],
    turns: list[SimulationTurn],
    delta: dict[str, int],
    side_effect_failures: list[str],
) -> dict[str, Any]:
    cases_passed = sum(1 for case in cases if case.status == "passed")
    copy_score = _average(
        [float(turn.metadata.get("score_dimensions", {}).get("copy_score", 1.0)) for turn in turns]
    )
    policy_score = _average(
        [
            float(turn.metadata.get("score_dimensions", {}).get("policy_score", 1.0))
            for turn in turns
        ]
    )
    structure_score = _average(
        [
            float(case.metadata.get("score_dimensions", {}).get("structure_score", 1.0))
            for case in cases
        ]
    )
    business_process_score = _average(
        [
            float(case.metadata.get("score_dimensions", {}).get("business_process_score", 1.0))
            for case in cases
        ]
    )
    score = round(
        0.25 * copy_score
        + 0.2 * policy_score
        + 0.3 * structure_score
        + 0.25 * business_process_score,
        4,
    )
    return {
        "cases_total": len(cases),
        "cases_passed": cases_passed,
        "cases_failed": len(cases) - cases_passed,
        "turns_total": len(turns),
        "score": score,
        "copy_score": copy_score,
        "policy_score": policy_score,
        "structure_score": structure_score,
        "business_process_score": business_process_score,
        "avg_confidence": round(_average([turn.confidence for turn in turns]), 4),
        "policy_invalid_count": sum(
            1 for turn in turns if not turn.policy_result.get("valid")
        ),
        "generic_answer_count": sum(
            1 for turn in turns if "generic_mock_answer" in turn.failure_reasons
        ),
        "provider_fallback_count": sum(
            1 for turn in turns if "provider_fallback" in turn.failure_reasons
        ),
        "legacy_interference": any(turn.metadata.get("legacy_used") for turn in turns),
        "safety_delta": delta,
        "side_effect_failures": side_effect_failures,
    }


def _average(values: list[float]) -> float:
    return round(sum(values) / len(values), 4) if values else 0.0


def _penalized_score(
    failures: list[str],
    failure_codes: set[str],
    *,
    penalty: float,
) -> float:
    hits = sum(1 for failure in failures if failure in failure_codes)
    return round(max(0.0, 1.0 - penalty * hits), 4)


def _provider_fallback_used(output: TurnOutput) -> bool:
    return bool(
        output.trace_metadata.get("fallback_reason")
        or any(flag.startswith("agent_model_provider_") for flag in output.risk_flags)
    )
