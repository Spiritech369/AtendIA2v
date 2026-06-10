from __future__ import annotations

import pytest

from atendia.agent_runtime.knowledge_tool_layer import TenantKnowledgeToolLayer
from atendia.agent_runtime.schemas import AdvisorBrainDecision, AdvisorBrainToolRequest
from tests.agent_runtime.expediente_preflight_utils import turn_context


@pytest.mark.asyncio
async def test_document_check_v2_bank_statement_classifies_account_statement() -> None:
    context = turn_context(
        "Adjunto estado de cuenta marzo.",
        metadata={"attachments": [{"id": "att-edo-marzo", "document_type": "bank_statement"}]},
    )
    result = (
        await TenantKnowledgeToolLayer().execute(
            context=context,
            decision=AdvisorBrainDecision(
                understanding="Cliente adjunta estado de cuenta.",
                next_best_action="check_document",
                required_tools=[AdvisorBrainToolRequest(name="document.check")],
                response_plan="Clasificar documento.",
            ),
        )
    )[0]

    assert result.status == "succeeded"
    assert result.data["documents_detected"][0]["document_type"] == "estados_cuenta_recientes"
