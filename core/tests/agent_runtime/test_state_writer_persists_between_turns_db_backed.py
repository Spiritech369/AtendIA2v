from __future__ import annotations

import json
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from atendia.agent_runtime.advisor_pipeline import AdvisorFirstAgentProvider
from atendia.agent_runtime.agent_service import AgentService
from atendia.agent_runtime.context_builder import ContextBuilder
from atendia.agent_runtime.schemas import TurnContext, TurnInput
from atendia.agent_runtime.semantic_interpreter import (
    SemanticAdvisorBrain,
    SemanticInterpretation,
)
from atendia.config import get_settings
from tests.agent_runtime.runtime_v2_parity_helpers import (
    DINAMO_TENANT_ID,
    outbox_count,
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


class _SequenceSemanticInterpreterProvider:
    def __init__(self, interpretations: list[dict[str, Any]]) -> None:
        self._interpretations = [
            SemanticInterpretation.model_validate(item) for item in interpretations
        ]
        self.contexts: list[TurnContext] = []

    async def interpret(self, context: TurnContext) -> SemanticInterpretation:
        self.contexts.append(context)
        return self._interpretations.pop(0)


@pytest.mark.integration_db
@pytest.mark.asyncio
async def test_state_writer_persists_between_turns_db_backed(db_session) -> None:
    _, conversation_id = await seed_runtime_conversation(db_session)
    interpreter = _SequenceSemanticInterpreterProvider(
        [
            {
                "intent": "credit_quote",
                "semantic_understanding": (
                    "Cliente quiere cotizar Skeleton a credito y menciona buro."
                ),
                "proposed_fields": {},
                "missing_field": "income_type",
                "required_tools": [
                    {"name": "catalog.search", "payload": {"query": "Skeleton"}},
                    {"name": "faq.lookup", "payload": {"query": "buro"}},
                ],
                "response_plan": "Validar modelo y buro; pedir ingresos.",
                "confidence": 0.91,
            },
            {
                "intent": "credit_quote",
                "semantic_understanding": (
                    "Cliente indica que le pagan por tarjeta; se debe resolver plan."
                ),
                "pending_slot_answered": "income_type",
                "income": {
                    "present": True,
                    "candidate": "nomina_tarjeta",
                    "evidence": "me pagan por tarjeta",
                    "confidence": 0.93,
                    "needs_clarification": False,
                },
                "proposed_fields": {},
                "missing_field": "employment_seniority",
                "required_tools": [],
                "response_plan": "Validar ingreso contra requisitos y pedir antiguedad.",
                "confidence": 0.93,
            },
        ]
    )
    provider = AdvisorFirstAgentProvider(
        advisor_brain=SemanticAdvisorBrain(interpreter=interpreter)
    )
    service = AgentService(session=db_session, provider=provider)

    first = await service.handle_turn(
        tenant_id=str(DINAMO_TENANT_ID),
        conversation_id=str(conversation_id),
        inbound_text="Hola, vi una Skeleton, cuanto sale a credito? Estoy en buro.",
        turn_number=1,
        mode="no_send",
    )
    await db_session.commit()

    assert first.output is not None
    assert first.send.mode == "no_send"
    assert first.send.outbox_write_attempted is False
    assert await outbox_count(db_session) == 0
    extracted = await _extracted_data(db_session, conversation_id)
    assert "Skeleton 400 CC" in json.dumps(
        extracted["product_selection"]["value"],
        ensure_ascii=False,
    )
    assert extracted["_runtime_v2"]["pending_slot"] == "income_type"

    second = await service.handle_turn(
        tenant_id=str(DINAMO_TENANT_ID),
        conversation_id=str(conversation_id),
        inbound_text="me pagan por tarjeta",
        turn_number=2,
        mode="no_send",
    )
    await db_session.commit()

    assert second.output is not None
    assert second.send.outbox_write_attempted is False
    assert await outbox_count(db_session) == 0
    extracted = await _extracted_data(db_session, conversation_id)
    assert extracted["plan_selection"]["value"] == "10%"
    assert extracted["down_payment_percent"]["value"] == 10
    assert extracted["_runtime_v2"]["pending_slot"] == "employment_seniority"

    next_context = await ContextBuilder(db_session).build(
        TurnInput(
            tenant_id=str(DINAMO_TENANT_ID),
            conversation_id=str(conversation_id),
            inbound_text="tengo 2 anos",
            turn_number=3,
        )
    )
    assert "Skeleton 400 CC" in json.dumps(
        next_context.memory.salient_facts["product_selection"],
        ensure_ascii=False,
    )
    assert next_context.memory.salient_facts["plan_selection"] == "10%"
    assert next_context.memory.metadata["pending_slot"] == "employment_seniority"


async def _extracted_data(
    session: AsyncSession,
    conversation_id,
) -> dict[str, Any]:
    return dict(
        (
            await session.execute(
                text(
                    """SELECT extracted_data
                    FROM conversation_state
                    WHERE conversation_id = :conversation_id"""
                ),
                {"conversation_id": conversation_id},
            )
        ).scalar_one()
        or {}
    )
