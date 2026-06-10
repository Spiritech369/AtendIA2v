from __future__ import annotations

import pytest

from atendia.agent_runtime.knowledge_tool_layer import TenantKnowledgeToolLayer
from atendia.agent_runtime.schemas import AdvisorBrainDecision, AdvisorBrainToolRequest
from tests.agent_runtime.expediente_preflight_utils import turn_context


@pytest.mark.asyncio
async def test_requirements_lookup_reads_expedientes_source() -> None:
    context = turn_context("que papeles ocupo")
    result = (
        await TenantKnowledgeToolLayer().execute(
            context=context,
            decision=AdvisorBrainDecision(
                understanding="Cliente pide requisitos.",
                next_best_action="lookup_requirements",
                required_tools=[
                    AdvisorBrainToolRequest(
                        name="requirements.lookup",
                        payload={"plan_credito": "10%"},
                    )
                ],
                response_plan="Responder requisitos estructurados.",
            ),
        )
    )[0]

    assert result.status == "succeeded"
    assert result.data["source_path"] == "docs/tenant_sources/dinamo/Requisitos_Credito_Dinamo.json"
    assert result.data["plan_id"] == "nomina_tarjeta_10"
    assert "Un mes de n" in " ".join(result.data["requirements"])
