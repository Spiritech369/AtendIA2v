from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import UUID

from atendia.agent_runtime.advisor_pipeline import AdvisorFirstAgentProvider
from atendia.agent_runtime.schemas import (
    ContactFieldDefinitionContext,
    ConversationMemoryContext,
    CustomerContext,
    MessageContext,
    TenantRuntimeConfigContext,
    TurnContext,
    TurnOutput,
)
from atendia.agent_runtime.semantic_interpreter import (
    SemanticAdvisorBrain,
    SemanticInterpretation,
    build_semantic_interpreter_payload,
)
from atendia.agent_runtime.tenant_domain_contract import (
    apply_tenant_domain_contract,
    load_tenant_domain_contract,
)

DINAMO_TENANT_ID = UUID("6ad78236-1fc9-467a-858d-90d248d57ee5")
DINAMO_AGENT_ID = UUID("c169deec-226d-55b7-bd07-270f339e75a6")
FIXTURE_DIR = Path(__file__).parent / "fixtures" / "tenant_domain_contracts"


class SequenceSemanticInterpreterProvider:
    def __init__(self, interpretations: list[dict[str, Any]]) -> None:
        self._interpretations = list(interpretations)
        self.calls: list[dict[str, Any]] = []

    async def interpret(self, context: TurnContext) -> SemanticInterpretation:
        self.calls.append(build_semantic_interpreter_payload(context))
        if not self._interpretations:
            raise AssertionError("no semantic interpretation left for test turn")
        return SemanticInterpretation.model_validate(self._interpretations.pop(0))


def dinamo_tenant_runtime_config() -> TenantRuntimeConfigContext:
    sources = {
        "catalog": "docs/tenant_sources/dinamo/CatalogoMotos2026_DINAMO.json",
        "requirements": "docs/tenant_sources/dinamo/Requisitos_Credito_Dinamo.json",
        "faq": "docs/tenant_sources/dinamo/FAQ_DINAMO.json",
    }
    config = TenantRuntimeConfigContext(
        knowledge_sources=list(sources.values()),
        metadata={
            "knowledge_os": {
                "sources": {key: {"path": value} for key, value in sources.items()},
                "mode": "tenant_structured_sources",
            }
        },
    )
    result = load_tenant_domain_contract(
        json.loads((FIXTURE_DIR / "dinamo_motos_nl_shadow.json").read_text(encoding="utf-8")),
        tenant_id=str(DINAMO_TENANT_ID),
        agent_id=str(DINAMO_AGENT_ID),
    )
    return apply_tenant_domain_contract(config, result)


def turn_context(
    inbound: str,
    *,
    messages: list[MessageContext] | None = None,
    memory: ConversationMemoryContext | None = None,
    customer_attrs: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    turn_number: int | None = None,
) -> TurnContext:
    config = dinamo_tenant_runtime_config()
    return TurnContext(
        tenant_id=str(DINAMO_TENANT_ID),
        conversation_id="conversation-expediente-preflight",
        inbound_text=inbound,
        customer=CustomerContext(
            id="contact-expediente",
            phone_e164="+5218128889241",
            attrs=customer_attrs or {},
        ),
        messages=messages or [MessageContext(role="customer", text=inbound)],
        contact_fields=[
            ContactFieldDefinitionContext(
                key=key,
                label=str(meta.get("label") or key),
                field_type=str(meta.get("type") or "text"),
            )
            for key, meta in config.field_metadata.items()
        ],
        memory=memory or ConversationMemoryContext(),
        tenant_config=config,
        metadata={
            "agent_id": str(DINAMO_AGENT_ID),
            "no_send": True,
            "turn_number": turn_number,
            **(metadata or {}),
        },
    )


def field_values(output: TurnOutput, field_key: str) -> list[Any]:
    return [update.value for update in output.field_updates if update.field_key == field_key]


def latest_field(output: TurnOutput, field_key: str) -> Any:
    values = field_values(output, field_key)
    return values[-1] if values else None


def document_preflight_interpretations() -> list[dict[str, Any]]:
    return [
        _doc_turn("INE PDF", [{"id": "att-ine-pdf", "document_type": "ine_pdf"}]),
        _doc_turn("comprobante CFE", [{"id": "att-cfe", "document_type": "cfe"}]),
        _doc_turn(
            "estados de cuenta marzo y abril",
            [
                {"id": "att-edo-marzo", "document_type": "bank_statement", "month": "marzo"},
                {"id": "att-edo-abril", "document_type": "bank_statement", "month": "abril"},
            ],
        ),
        _evaluate_turn("no faltaban las nominas?"),
        _doc_turn(
            "1 recibo semanal de nomina",
            [
                {
                    "id": "att-nomina-semanal-1",
                    "document_type": "payroll_receipt",
                    "payroll_periodicity": "semanal",
                }
            ],
        ),
        _evaluate_turn("ya quedo?"),
    ]


async def run_documental_preflight() -> tuple[
    list[TurnOutput],
    SequenceSemanticInterpreterProvider,
]:
    turns = [
        {
            "text": "Adjunto INE PDF.",
            "attachments": [{"id": "att-ine-pdf", "document_type": "ine_pdf"}],
        },
        {
            "text": "Adjunto comprobante CFE.",
            "attachments": [{"id": "att-cfe", "document_type": "cfe"}],
        },
        {
            "text": "Adjunto estados de cuenta marzo y abril.",
            "attachments": [
                {"id": "att-edo-marzo", "document_type": "bank_statement", "month": "marzo"},
                {"id": "att-edo-abril", "document_type": "bank_statement", "month": "abril"},
            ],
        },
        {"text": "no faltaban las nominas?", "attachments": []},
        {
            "text": "Adjunto 1 recibo semanal de nomina.",
            "attachments": [
                {
                    "id": "att-nomina-semanal-1",
                    "document_type": "payroll_receipt",
                    "payroll_periodicity": "semanal",
                }
            ],
        },
        {"text": "ya quedo?", "attachments": []},
    ]
    interpreter = SequenceSemanticInterpreterProvider(document_preflight_interpretations())
    provider = AdvisorFirstAgentProvider(advisor_brain=SemanticAdvisorBrain(interpreter))
    messages: list[MessageContext] = []
    attrs: dict[str, Any] = {
        "plan_selection": "10%",
        "down_payment_percent": 10,
        "product_selection": "Skeleton 400 CC",
        "quote_snapshot_id": "quote-dinamo-skeleton-400-plan-10",
        "quote_sent": True,
        "requirements_requested": True,
        "payroll_periodicity": "semanal",
    }
    salient_facts = dict(attrs)
    outputs: list[TurnOutput] = []
    for index, turn in enumerate(turns, start=1):
        text = str(turn["text"])
        messages.append(MessageContext(role="customer", text=text))
        context = turn_context(
            text,
            messages=list(messages),
            memory=ConversationMemoryContext(salient_facts=dict(salient_facts)),
            customer_attrs=dict(attrs),
            metadata={"attachments": turn["attachments"], "no_send": True},
            turn_number=index,
        )
        output = await provider.generate(context)
        outputs.append(output)
        messages.append(MessageContext(role="agent", text=output.final_message))
        for update in output.field_updates:
            attrs[update.field_key] = update.value
            salient_facts[update.field_key] = update.value
    return outputs, interpreter


def _doc_turn(text: str, attachments: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "intent": "document_received",
        "semantic_understanding": f"Cliente adjunta {text}.",
        "proposed_fields": {},
        "missing_field": None,
        "required_tools": [
            {
                "name": "document.check",
                "input": {"attachments": attachments},
                "reason": "Classify received document attachment.",
                "evidence": [text],
            },
            {
                "name": "expediente.evaluate",
                "input": {"plan_credito": "10%", "payroll_periodicity": "semanal"},
                "reason": "Evaluate expediente completeness from Expedientes.",
                "evidence": [text],
            },
        ],
        "response_plan": "Responder estado documental validado.",
        "confidence": 0.92,
        "needs_human": False,
        "risk_flags": [],
    }


def _evaluate_turn(text: str) -> dict[str, Any]:
    return {
        "intent": "document_status_question",
        "semantic_understanding": "Cliente pregunta por faltantes del expediente.",
        "proposed_fields": {},
        "missing_field": None,
        "required_tools": [
            {
                "name": "expediente.evaluate",
                "input": {"plan_credito": "10%", "payroll_periodicity": "semanal"},
                "reason": "Evaluate current expediente before answering.",
                "evidence": [text],
            }
        ],
        "response_plan": "Explicar faltantes sin declarar expediente completo.",
        "confidence": 0.9,
        "needs_human": False,
        "risk_flags": [],
    }
