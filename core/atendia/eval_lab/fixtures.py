from __future__ import annotations

from atendia.agent_runtime.schemas import (
    ActionRequest,
    FieldUpdate,
    KnowledgeCitation,
    LifecycleUpdate,
    TurnContext,
    TurnOutput,
)
from atendia.eval_lab.schemas import EvalScenario


class FixtureAgentProvider:
    """Scenario-aware provider for offline harness tests and demos."""

    async def generate(self, context: TurnContext) -> TurnOutput:
        text = context.inbound_text.casefold()
        evidence = [context.inbound_text]
        trace = {
            "provider": "eval_lab_fixture",
            "scenario_id": context.metadata.get("scenario_id"),
            "executed_actions": False,
        }
        if any(term in text for term in ["humano", "asesor", "persona"]):
            return TurnOutput(
                final_message="Te conecto con una persona del equipo para ayudarte.",
                actions=[
                    ActionRequest(
                        name="assign_conversation",
                        payload={"agent_id": "human_queue"},
                        reason="Customer requested a human.",
                        evidence=evidence,
                    )
                ],
                confidence=0.92,
                needs_human=True,
                trace_metadata=trace,
            )
        if any(term in text for term in ["presupuesto", "budget"]):
            return TurnOutput(
                final_message="Gracias, tomo nota de tu presupuesto.",
                field_updates=[
                    FieldUpdate(
                        field_key="budget",
                        value=_extract_budget(text),
                        reason="Customer shared a budget.",
                        evidence=evidence,
                        confidence=0.86,
                        source="customer_message",
                    )
                ],
                confidence=0.86,
                trace_metadata=trace,
            )
        if any(term in text for term in ["cita", "agendar", "mañana", "manana"]):
            return TurnOutput(
                final_message="Puedo ayudarte a agendar la cita. ¿Que horario prefieres?",
                lifecycle_update=LifecycleUpdate(
                    target_stage="appointment_requested",
                    reason="Customer asked to schedule an appointment.",
                    evidence=evidence,
                    confidence=0.82,
                ),
                confidence=0.82,
                trace_metadata=trace,
            )
        if any(term in text for term in ["precio", "cuesta", "costo"]):
            citation = context.knowledge_citations[:1]
            return TurnOutput(
                final_message=(
                    "El precio depende de la opcion consultada; uso la fuente disponible "
                    "para confirmarlo."
                ),
                knowledge_citations=citation,
                confidence=0.78 if citation else 0.42,
                needs_human=not bool(citation),
                risk_flags=[] if citation else ["knowledge_gap"],
                trace_metadata=trace,
            )
        if any(term in text for term in ["horario", "abren", "cierran"]):
            return TurnOutput(
                final_message="El horario disponible esta en las fuentes del negocio.",
                knowledge_citations=context.knowledge_citations[:1],
                confidence=0.78,
                trace_metadata=trace,
            )
        if any(term in text for term in ["garantia extendida secreta", "no presente"]):
            return TurnOutput(
                final_message="No tengo informacion suficiente en la base para confirmarlo.",
                confidence=0.35,
                needs_human=True,
                risk_flags=["knowledge_gap"],
                trace_metadata=trace,
            )
        return TurnOutput(
            final_message="Entendido. Para avanzar, confirmame el detalle que prefieres.",
            confidence=0.68,
            trace_metadata=trace,
        )


def generic_scenarios() -> list[EvalScenario]:
    return [
        EvalScenario(
            id="generic-price",
            name="Cliente pregunta precio",
            input_message="Cuanto cuesta el servicio premium?",
            knowledge_sources=[_citation("Catalogo", "Servicio premium desde $199.")],
            expected_behaviors=["answer_current_question"],
            forbidden_behaviors=["inventar precio sin fuente"],
        ),
        EvalScenario(
            id="generic-appointment",
            name="Cliente pide cita",
            input_message="Quiero agendar una cita para mañana",
            expected_behaviors=["answer_current_question"],
            expected_lifecycle="appointment_requested",
        ),
        EvalScenario(
            id="generic-human",
            name="Cliente pide humano",
            input_message="Quiero hablar con un asesor humano",
            expected_behaviors=["escalate_to_human"],
            expected_actions=["assign_conversation"],
        ),
        EvalScenario(
            id="generic-budget",
            name="Cliente manda dato de presupuesto",
            input_message="Mi presupuesto es 5000",
            contact_fields={"budget": None},
            expected_behaviors=["capture_budget"],
            expected_field_updates=["budget"],
        ),
        EvalScenario(
            id="generic-hours",
            name="Cliente pregunta horario",
            input_message="Que horario tienen?",
            knowledge_sources=[_citation("Horarios", "Atendemos de lunes a viernes.")],
            expected_behaviors=["answer_current_question"],
        ),
        EvalScenario(
            id="generic-conflicting-field",
            name="Cliente contradice dato anterior",
            input_message="Me equivoque, mi presupuesto no es 3000, es 5000",
            contact_fields={"budget": "3000"},
            expected_behaviors=["handle_correction"],
            expected_field_updates=["budget"],
        ),
        EvalScenario(
            id="generic-kb-gap",
            name="Cliente pregunta algo no presente en KB",
            input_message="Tienen garantia extendida secreta no presente en KB?",
            expected_behaviors=["knowledge_gap_safe"],
            forbidden_behaviors=["si tenemos", "claro que si"],
        ),
        EvalScenario(
            id="generic-short-yes",
            name='Cliente envia mensaje corto: "si"',
            input_message="sí",
            conversation_history=[
                {
                    "role": "agent",
                    "text": "Quieres que te comparta opciones disponibles?",
                }
            ],
            expected_behaviors=["handle_short_reply"],
        ),
        EvalScenario(
            id="generic-short-that",
            name='Cliente envia mensaje corto: "esa"',
            input_message="esa",
            conversation_history=[
                {
                    "role": "agent",
                    "text": "Prefieres la opcion A o la opcion B?",
                }
            ],
            expected_behaviors=["handle_short_reply"],
        ),
        EvalScenario(
            id="generic-short-tomorrow",
            name='Cliente envia mensaje corto: "mañana"',
            input_message="mañana",
            conversation_history=[
                {
                    "role": "agent",
                    "text": "Que dia te gustaria agendar?",
                }
            ],
            expected_behaviors=["answer_current_question"],
            expected_lifecycle="appointment_requested",
        ),
    ]


def blueprint_scenarios() -> dict[str, list[EvalScenario]]:
    return {
        "automotive/motos": [
            EvalScenario(
                id="blueprint-motos-price",
                name="Motos: pregunta precio de modelo",
                vertical="automotive/motos",
                input_message="Que precio tiene el modelo de entrada?",
                knowledge_sources=[_citation("Catalogo motos", "Modelo de entrada desde $1000.")],
                expected_behaviors=["answer_current_question"],
            )
        ],
        "automotive/autos": [
            EvalScenario(
                id="blueprint-autos-test-drive",
                name="Autos: pide prueba de manejo",
                vertical="automotive/autos",
                input_message="Quiero agendar una prueba de manejo mañana",
                expected_behaviors=["answer_current_question"],
                expected_lifecycle="appointment_requested",
            )
        ],
        "inmuebles": [
            EvalScenario(
                id="blueprint-real-estate-budget",
                name="Inmuebles: comparte presupuesto",
                vertical="inmuebles",
                input_message="Busco departamento y mi presupuesto es 250000",
                expected_behaviors=["capture_budget"],
                expected_field_updates=["budget"],
            )
        ],
        "dental/clinics": [
            EvalScenario(
                id="blueprint-dental-hours",
                name="Dental: pregunta horarios",
                vertical="dental/clinics",
                input_message="Que horario tiene la clinica?",
                knowledge_sources=[_citation("Horarios clinica", "Atencion lunes a sabado.")],
                expected_behaviors=["answer_current_question"],
            )
        ],
        "beauty/barber/spa": [
            EvalScenario(
                id="blueprint-beauty-appointment",
                name="Beauty: solicita cita",
                vertical="beauty/barber/spa",
                input_message="Quiero una cita para corte mañana",
                expected_behaviors=["answer_current_question"],
                expected_lifecycle="appointment_requested",
            )
        ],
    }


def all_fixture_scenarios(*, include_blueprints: bool = False) -> list[EvalScenario]:
    scenarios = generic_scenarios()
    if include_blueprints:
        for values in blueprint_scenarios().values():
            scenarios.extend(values)
    return scenarios


def _citation(title: str, snippet: str) -> KnowledgeCitation:
    return KnowledgeCitation(
        source_id="00000000-0000-4000-8000-000000000100",
        title=title,
        snippet=snippet,
        score=0.9,
        metadata={"fixture": True},
    )


def _extract_budget(text: str) -> str:
    digits = "".join(char for char in text if char.isdigit())
    return digits or "unknown"
