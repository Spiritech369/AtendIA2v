from __future__ import annotations

import pytest

from atendia.agent_runtime.knowledge_tool_layer import TenantKnowledgeToolLayer
from atendia.agent_runtime.schemas import AdvisorBrainDecision, AdvisorBrainToolRequest
from tests.agent_runtime.expediente_preflight_utils import turn_context


@pytest.mark.asyncio
async def test_document_check_v2_ine_pdf_classifies_without_completeness() -> None:
    context = turn_context(
        "Adjunto INE PDF.",
        metadata={"attachments": [{"id": "att-ine", "document_type": "ine_pdf"}]},
    )
    result = (
        await TenantKnowledgeToolLayer().execute(
            context=context,
            decision=AdvisorBrainDecision(
                understanding="Cliente adjunta INE.",
                next_best_action="check_document",
                required_tools=[AdvisorBrainToolRequest(name="document.check")],
                response_plan="Clasificar documento.",
            ),
        )
    )[0]

    assert result.status == "succeeded"
    assert result.data["classification_only"] is True
    assert result.data["documents_detected"][0]["document_type"] == "ine_ambos_lados"
    assert "requirements_complete" not in result.data
