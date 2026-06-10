from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from atendia.agent_runtime.schemas import TurnOutput
from atendia.agent_runtime.send_adapter import RuntimeV2SendAdapter
from atendia.config import get_settings
from tests.agent_runtime.runtime_v2_parity_helpers import (
    DINAMO_TENANT_ID,
    outbox_count,
    runtime_config,
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
async def test_send_adapter_is_only_difference_between_no_send_and_live(
    db_session,
) -> None:
    contact_id, conversation_id = await seed_runtime_conversation(db_session)
    adapter = RuntimeV2SendAdapter()
    output = TurnOutput(
        final_message="Mensaje validado desde TurnOutput.final_message.",
        confidence=0.9,
        trace_metadata={"universal_turn_trace": {"trace_id": "send-adapter-test"}},
    )
    enabled_runtime_config = runtime_config(
        send_enabled=True,
        outbox_enabled=True,
        live_send_enabled=True,
        single_contact_smoke_enabled=True,
        send_scope="approved_contact_only",
        allowed_contact_ids=[str(contact_id)],
    )

    no_send = await adapter.apply(
        mode="no_send",
        session=db_session,
        runtime_config=enabled_runtime_config,
        global_send_enabled=True,
        tenant_id=str(DINAMO_TENANT_ID),
        conversation_id=str(conversation_id),
        turn_number=1,
        contact_id=str(contact_id),
        phone_e164="+5215555550037",
        recipient_phone_e164="+5215555550037",
        output=output,
        provider_fallback_detected=False,
    )
    await db_session.flush()

    assert no_send.delivery_status["send_status"] == "no_send"
    assert no_send.outbox_write_attempted is False
    assert no_send.outbound_messages is None
    assert await outbox_count(db_session) == 0

    live_candidate = await adapter.apply(
        mode="live_candidate",
        session=db_session,
        runtime_config=enabled_runtime_config,
        global_send_enabled=True,
        tenant_id=str(DINAMO_TENANT_ID),
        conversation_id=str(conversation_id),
        turn_number=1,
        contact_id=str(contact_id),
        phone_e164="+5215555550037",
        recipient_phone_e164="+5215555550037",
        output=output,
        provider_fallback_detected=False,
    )
    await db_session.flush()

    assert live_candidate.delivery_status["send_status"] == "prepared"
    assert live_candidate.outbox_write_attempted is True
    assert live_candidate.outbound_messages == [output.final_message]
    assert await outbox_count(db_session) == 1
