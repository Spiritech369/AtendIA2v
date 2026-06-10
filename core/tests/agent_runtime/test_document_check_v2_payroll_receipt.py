from __future__ import annotations

import pytest

from atendia.agent_runtime.knowledge_tool_layer import TenantKnowledgeToolLayer
from atendia.agent_runtime.schemas import AdvisorBrainDecision, AdvisorBrainToolRequest
from tests.agent_runtime.expediente_preflight_utils import turn_context


@pytest.mark.asyncio
async def test_document_check_v2_payroll_receipt_keeps_periodicity_metadata() -> None:
    context = turn_context(
        "Adjunto recibo semanal de nomina.",
        metadata={
            "attachments": [
                {
                    "id": "att-nomina-1",
                    "document_type": "payroll_receipt",
                    "payroll_periodicity": "semanal",
                }
            ]
        },
    )
    result = (
        await TenantKnowledgeToolLayer().execute(
            context=context,
            decision=AdvisorBrainDecision(
                understanding="Cliente adjunta recibo de nomina.",
                next_best_action="check_document",
                required_tools=[AdvisorBrainToolRequest(name="document.check")],
                response_plan="Clasificar documento.",
            ),
        )
    )[0]

    detected = result.data["documents_detected"][0]
    assert result.status == "succeeded"
    assert detected["document_type"] == "nomina_1_mes_dentro_estado_cuenta"
    assert detected["metadata"]["payroll_periodicity"] == "semanal"


@pytest.mark.asyncio
async def test_document_check_v2_operational_payroll_id_wins_over_account_text() -> None:
    context = turn_context(
        "Adjunto una nomina semanal.",
        metadata={
            "attachments": [
                {
                    "id": "att-nomina-operational-id",
                    "document_type": "nomina_1_mes_dentro_estado_cuenta",
                    "payroll_periodicity": "semanal",
                }
            ]
        },
    )
    result = (
        await TenantKnowledgeToolLayer().execute(
            context=context,
            decision=AdvisorBrainDecision(
                understanding="Cliente adjunta nomina con id operativo.",
                next_best_action="check_document",
                required_tools=[AdvisorBrainToolRequest(name="document.check")],
                response_plan="Clasificar documento.",
            ),
        )
    )[0]

    detected = result.data["documents_detected"][0]
    assert result.status == "succeeded"
    assert detected["document_type"] == "nomina_1_mes_dentro_estado_cuenta"
    assert detected["metadata"]["payroll_periodicity"] == "semanal"
