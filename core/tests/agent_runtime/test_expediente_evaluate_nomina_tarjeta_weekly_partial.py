from __future__ import annotations

import pytest

from atendia.agent_runtime.knowledge_tool_layer import TenantKnowledgeToolLayer
from atendia.agent_runtime.schemas import AdvisorBrainDecision, AdvisorBrainToolRequest
from tests.agent_runtime.expediente_preflight_utils import turn_context


@pytest.mark.asyncio
async def test_expediente_evaluate_nomina_tarjeta_weekly_partial() -> None:
    attachments = [
        {"id": "att-ine", "document_type": "ine_pdf"},
        {"id": "att-cfe", "document_type": "cfe"},
        {"id": "att-edo-marzo", "document_type": "bank_statement", "month": "marzo"},
        {"id": "att-edo-abril", "document_type": "bank_statement", "month": "abril"},
        {
            "id": "att-nomina-1",
            "document_type": "payroll_receipt",
            "payroll_periodicity": "semanal",
        },
    ]
    results = await TenantKnowledgeToolLayer().execute(
        context=turn_context(
            "Adjunto expediente parcial.",
            customer_attrs={"plan_selection": "10%", "payroll_periodicity": "semanal"},
            metadata={"attachments": attachments},
        ),
        decision=AdvisorBrainDecision(
            understanding="Cliente adjunta documentos de expediente.",
            next_best_action="evaluate_expediente",
            required_tools=[
                AdvisorBrainToolRequest(name="document.check"),
                AdvisorBrainToolRequest(
                    name="expediente.evaluate",
                    payload={"plan_credito": "10%", "payroll_periodicity": "semanal"},
                ),
            ],
            response_plan="Explicar faltantes.",
        ),
    )

    evaluate = results[-1]
    checklist = evaluate.data["Docs_Checklist"]
    payroll = next(
        item
        for item in checklist["items"]
        if item["key"] == "nomina_1_mes_dentro_estado_cuenta"
    )

    assert evaluate.status == "succeeded"
    assert evaluate.data["contract"] == "Expedientes"
    assert evaluate.data["requirements_complete"] is False
    assert payroll["nominas_requeridas"] == 4
    assert payroll["nominas_recibidas"] == 1
    assert payroll["nominas_faltantes"] == 3
    assert evaluate.data["missing_documents"][0]["key"] == (
        "nomina_1_mes_dentro_estado_cuenta"
    )
    assert evaluate.data["missing_documents"][0]["missing_count"] == 3
