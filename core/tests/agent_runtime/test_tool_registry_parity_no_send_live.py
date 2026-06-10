from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from atendia.agent_runtime.advisor_pipeline import AdvisorFirstAgentProvider
from atendia.agent_runtime.context_builder import ContextBuilder
from atendia.agent_runtime.schemas import TurnInput
from atendia.agent_runtime.semantic_interpreter import (
    MockSemanticInterpreterProvider,
    SemanticAdvisorBrain,
)
from atendia.config import get_settings
from tests.agent_runtime.runtime_v2_parity_helpers import (
    DINAMO_AGENT_ID,
    DINAMO_TENANT_ID,
    seed_runtime_conversation,
)


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine(get_settings().database_url)
    session_factory = async_sessionmaker(
        engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )
    async with session_factory() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@pytest.mark.integration_db
@pytest.mark.asyncio
async def test_tool_registry_parity_no_send_live(db_session) -> None:
    _, conversation_id = await seed_runtime_conversation(db_session)
    interpretation = {
        "intent": "credit_quote",
        "semantic_understanding": "Cliente quiere Skeleton a credito y menciona buro.",
        "proposed_fields": {},
        "missing_field": "income_type",
        "required_tools": [
            {"name": "catalog.search", "input": {"query": "Skeleton"}},
            {"name": "faq.lookup", "input": {"query": "buro"}},
        ],
        "response_plan": "Validar modelo y politica de buro antes de pedir ingresos.",
        "confidence": 0.91,
    }
    provider = AdvisorFirstAgentProvider(
        advisor_brain=SemanticAdvisorBrain(
            interpreter=MockSemanticInterpreterProvider(interpretation)
        )
    )
    no_send_context = await ContextBuilder(db_session).build(
        TurnInput(
            tenant_id=str(DINAMO_TENANT_ID),
            conversation_id=str(conversation_id),
            inbound_text="Hola, vi una Skeleton, cuanto sale a credito? Estoy en buro.",
            turn_number=1,
            metadata={
                "agent_id": str(DINAMO_AGENT_ID),
                "agent_service_mode": "no_send",
            },
        )
    )
    live_context = await ContextBuilder(db_session).build(
        TurnInput(
            tenant_id=str(DINAMO_TENANT_ID),
            conversation_id=str(conversation_id),
            inbound_text="Hola, vi una Skeleton, cuanto sale a credito? Estoy en buro.",
            turn_number=1,
            metadata={
                "agent_id": str(DINAMO_AGENT_ID),
                "agent_service_mode": "live_candidate",
            },
        )
    )

    no_send_output = await provider.generate(no_send_context)
    live_output = await provider.generate(live_context)

    assert _requested_tools(no_send_output) == _requested_tools(live_output)
    assert _tool_results(no_send_output) == _tool_results(live_output)
    assert ("catalog.search", "succeeded") in _tool_results(no_send_output)
    assert ("faq.lookup", "succeeded") in _tool_results(no_send_output)


def _requested_tools(output) -> list[str]:
    return [
        item["name"]
        for item in output.trace_metadata["advisor_brain"]["required_tools"]
    ]


def _tool_results(output) -> list[tuple[str, str]]:
    return [
        (item["tool_name"], item["status"])
        for item in output.trace_metadata["tool_results"]
    ]
