from __future__ import annotations

from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from atendia.agent_runtime.context_builder import ContextBuilder
from atendia.agent_runtime.schemas import TurnInput
from atendia.config import get_settings
from tests.agent_runtime.runtime_v2_parity_helpers import (
    DINAMO_AGENT_ID,
    DINAMO_TENANT_ID,
    insert_history,
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
async def test_context_builder_live_no_send_parity(db_session) -> None:
    _, conversation_id = await seed_runtime_conversation(
        db_session,
        extracted_data={
            "product_selection": {"value": "Skeleton 400 CC", "source": "catalog.search"},
            "_runtime_v2": {
                "pending_slot": "income_type",
                "question_slot": "income_type",
            },
        },
    )
    await insert_history(db_session, conversation_id=conversation_id, count=25)

    no_send = await ContextBuilder(db_session).build(
        TurnInput(
            tenant_id=str(DINAMO_TENANT_ID),
            conversation_id=str(conversation_id),
            inbound_text="me pagan por tarjeta",
            turn_number=2,
            metadata={
                "agent_id": str(DINAMO_AGENT_ID),
                "agent_service_mode": "no_send",
                "send_execution_mode": "no_send",
            },
        )
    )
    live_candidate = await ContextBuilder(db_session).build(
        TurnInput(
            tenant_id=str(DINAMO_TENANT_ID),
            conversation_id=str(conversation_id),
            inbound_text="me pagan por tarjeta",
            turn_number=2,
            metadata={
                "agent_id": str(DINAMO_AGENT_ID),
                "agent_service_mode": "live_candidate",
                "send_execution_mode": "live_candidate",
            },
        )
    )

    assert len(no_send.messages) == 21
    assert no_send.messages[0].text == "historial 5"
    assert "docs/tenant_sources/dinamo/CatalogoMotos2026_DINAMO.json" in (
        no_send.tenant_config.knowledge_sources
    )
    assert no_send.tenant_config.metadata["knowledge_os"]["sources"]["requirements"][
        "path"
    ].endswith("Requisitos_Credito_Dinamo.json")
    assert no_send.memory.metadata["pending_slot"] == "income_type"
    assert _sanitize(no_send.model_dump(mode="json")) == _sanitize(
        live_candidate.model_dump(mode="json")
    )


def _sanitize(context: dict[str, Any]) -> dict[str, Any]:
    metadata = dict(context.get("metadata") or {})
    metadata.pop("agent_service_mode", None)
    metadata.pop("send_execution_mode", None)
    context = dict(context)
    context["metadata"] = metadata
    return context
