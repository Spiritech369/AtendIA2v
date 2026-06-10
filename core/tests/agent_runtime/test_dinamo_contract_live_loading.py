from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from atendia.agent_runtime.context_builder import ContextBuilder
from atendia.agent_runtime.schemas import TurnInput
from atendia.config import get_settings
from atendia.contracts.message import Message, MessageDirection
from atendia.runner.composer_protocol import ComposerInput, ComposerOutput
from atendia.runner.conversation_runner import ConversationRunner

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "tenant_domain_contracts"
DINAMO_TENANT_ID = UUID("6ad78236-1fc9-467a-858d-90d248d57ee5")
DINAMO_AGENT_ID = UUID("c169deec-226d-55b7-bd07-270f339e75a6")


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


class _UnusedNLU:
    async def classify(self, **kwargs):  # pragma: no cover - runtime v2 path only
        raise AssertionError("legacy NLU must not run for runtime v2 tenant")


class _RecordingComposer:
    def __init__(self) -> None:
        self.call_count = 0

    async def compose(
        self,
        *,
        input: ComposerInput,
    ) -> tuple[ComposerOutput, None]:  # pragma: no cover - legacy path only
        self.call_count += 1
        return ComposerOutput(messages=["legacy composer text"]), None


@pytest.mark.integration_db
@pytest.mark.asyncio
async def test_context_builder_loads_dinamo_contract_from_live_runtime_config_shape(
    db_session,
):
    _, conversation_id = await _seed_runtime_conversation(
        db_session,
        runtime_overrides={"tenant_domain_contract": _dinamo_contract()},
    )

    context = await ContextBuilder(db_session).build(
        TurnInput(
            tenant_id=str(DINAMO_TENANT_ID),
            conversation_id=str(conversation_id),
            inbound_text="me interesa la skeleton a credito, traigo buro",
            metadata={"agent_id": str(DINAMO_AGENT_ID), "turn_number": 1},
        )
    )

    assert context.tenant_config.domain == "vehicle_credit_sales"
    assert context.tenant_config.safe_mode is False
    assert {
        "catalog.search",
        "credit_plan.resolve",
        "quote.resolve",
        "requirements.lookup",
        "faq.lookup",
        "document.check",
    } <= set(context.tenant_config.tool_metadata)
    assert {
        "product_selection",
        "plan_selection",
        "quote_snapshot_id",
        "requirements_complete",
    } <= set(context.tenant_config.field_metadata)
    assert {
        "mandatory_tool_guard",
        "quote_snapshot_guard",
        "no_approval_guard",
    } <= set(context.tenant_config.guard_metadata)
    assert context.metadata["tenant_domain_contract"]["domain"] == "vehicle_credit_sales"
    assert context.metadata["tenant_domain_contract"]["safe_mode"] is False


@pytest.mark.integration_db
@pytest.mark.asyncio
async def test_missing_contract_safe_mode_fails_closed_before_outbox(
    db_session,
    monkeypatch,
):
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_ENABLED", "true")
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_SEND_ENABLED", "true")
    get_settings.cache_clear()
    contact_id, conversation_id = await _seed_runtime_conversation(
        db_session,
        runtime_overrides={
            "tenant_domain_contract": None,
            "send_enabled": True,
            "outbox_enabled": True,
            "single_contact_smoke_enabled": True,
            "send_scope": "approved_contact_only",
            "allowed_contact_ids": [],
            "allowed_test_phones": ["+5215555550037"],
        },
    )
    await _allow_contact(db_session, contact_id)
    composer = _RecordingComposer()

    trace = await ConversationRunner(db_session, _UnusedNLU(), composer).run_turn(
        conversation_id=conversation_id,
        tenant_id=DINAMO_TENANT_ID,
        inbound=_inbound(conversation_id, "me interesa la skeleton a credito, traigo buro"),
        turn_number=1,
    )
    await db_session.commit()

    assert composer.call_count == 0
    assert trace.state_after["universal_turn_trace"] is not None
    assert trace.state_after["send_decision"]["allowed"] is False
    assert "tenant_domain_contract_safe_mode" in trace.state_after["send_decision"]["reasons"]
    assert trace.state_after["send_status"] == "blocked_by_policy"
    assert trace.state_after["customer_visible_message_sent"] is False
    assert trace.outbound_messages is None
    assert trace.state_after["outbox_write_attempted"] is False
    assert await _outbox_count(db_session) == 0

    universal = trace.state_after["universal_turn_trace"]
    assert universal["audit"]["tenant_domain_contract"]["safe_mode"] is True
    assert universal["tool_results"] == []
    workflow_results = trace.state_after["workflow_results"]
    assert all(result["side_effects_allowed"] is False for result in workflow_results)
    assert all(result["status"] != "executed" for result in workflow_results)


@pytest.mark.integration_db
@pytest.mark.asyncio
async def test_dinamo_contract_loaded_prepared_no_send_skeleton_credit_bureau(
    db_session,
    monkeypatch,
):
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_ENABLED", "true")
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_SEND_ENABLED", "true")
    get_settings.cache_clear()
    contact_id, conversation_id = await _seed_runtime_conversation(
        db_session,
        runtime_overrides={
            "tenant_domain_contract": _dinamo_contract(),
            "send_enabled": False,
            "outbox_enabled": False,
            "live_send_enabled": False,
            "single_contact_smoke_enabled": False,
            "send_scope": "approved_contact_only",
            "allowed_contact_ids": [],
            "allowed_test_phones": ["+5215555550037"],
        },
    )
    await _allow_contact(db_session, contact_id)
    composer = _RecordingComposer()

    trace = await ConversationRunner(db_session, _UnusedNLU(), composer).run_turn(
        conversation_id=conversation_id,
        tenant_id=DINAMO_TENANT_ID,
        inbound=_inbound(conversation_id, "me interesa la skeleton a credito, traigo buro"),
        turn_number=1,
    )
    await db_session.commit()

    assert composer.call_count == 0
    assert trace.state_after["universal_turn_trace"]["domain"] == "vehicle_credit_sales"
    assert trace.state_after["send_decision"]["allowed"] is False
    assert "tenant_send_disabled" in trace.state_after["send_decision"]["reasons"]
    assert "tenant_outbox_disabled" in trace.state_after["send_decision"]["reasons"]
    assert trace.state_after["send_status"] == "blocked_by_policy"
    assert trace.outbound_messages is None
    assert trace.state_after["outbox_write_attempted"] is False
    assert await _outbox_count(db_session) == 0

    final_message = trace.composer_output["final_message"]
    assert "Skeleton" in final_message
    assert "ingresos" in final_message
    assert "$" not in final_message
    assert "modelo quieres" not in final_message

    required_tools = _required_tool_names(trace.state_after["universal_turn_trace"])
    assert "catalog.search" in required_tools
    assert "faq.lookup" in required_tools
    assert "quote.resolve" not in required_tools
    assert trace.state_after["universal_turn_trace"]["gpt_understanding"][
        "missing_facts"
    ] == ["income_proof_type"]


async def _seed_runtime_conversation(
    session: AsyncSession,
    *,
    runtime_overrides: dict,
) -> tuple[UUID, UUID]:
    runtime_config = _runtime_config(**runtime_overrides)
    await session.execute(
        text(
            """INSERT INTO tenants (id, name, config)
            VALUES (:id, :name, CAST(:config AS jsonb))"""
        ),
        {
            "id": DINAMO_TENANT_ID,
            "name": "Dinamo Motos NL contract live loading test",
            "config": json.dumps({"agent_runtime_v2": runtime_config}),
        },
    )
    contact_id = (
        await session.execute(
            text(
                """INSERT INTO customers (tenant_id, phone_e164, name)
                VALUES (:tenant_id, '+5215555550037', 'Contacto contrato')
                RETURNING id"""
            ),
            {"tenant_id": DINAMO_TENANT_ID},
        )
    ).scalar_one()
    conversation_id = (
        await session.execute(
            text(
                """INSERT INTO conversations (tenant_id, customer_id, current_stage)
                VALUES (:tenant_id, :customer_id, 'qualify')
                RETURNING id"""
            ),
            {"tenant_id": DINAMO_TENANT_ID, "customer_id": contact_id},
        )
    ).scalar_one()
    await session.execute(
        text("INSERT INTO conversation_state (conversation_id) VALUES (:conversation_id)"),
        {"conversation_id": conversation_id},
    )
    await session.commit()
    return contact_id, conversation_id


def _runtime_config(**overrides) -> dict:
    contract_value = overrides.pop("tenant_domain_contract", _dinamo_contract())
    runtime_config = {
        "runtime_v2_enabled": True,
        "runtime_mode": "runtime_v2_single_contact_smoke_failed_no_send",
        "send_enabled": False,
        "outbox_enabled": False,
        "live_send_enabled": False,
        "actions_enabled": False,
        "workflow_side_effects_enabled": False,
        "workflow_events_enabled": False,
        "single_contact_smoke_enabled": False,
        "legacy_fallback_enabled": False,
        "provider_visible_fallback_enabled": False,
        "manual_recovery_visible_enabled": False,
        "canary_enabled": False,
        "open_production_enabled": False,
        "agent_id": str(DINAMO_AGENT_ID),
        "allowed_agent_ids": [str(DINAMO_AGENT_ID)],
        **overrides,
    }
    if contract_value is not None:
        runtime_config["tenant_domain_contract"] = contract_value
    return runtime_config


async def _allow_contact(session: AsyncSession, contact_id: UUID) -> None:
    await session.execute(
        text(
            """UPDATE tenants
            SET config = jsonb_set(
                config,
                '{agent_runtime_v2,allowed_contact_ids}',
                CAST(:allowed AS jsonb),
                true
            )
            WHERE id = :tenant_id"""
        ),
        {
            "tenant_id": DINAMO_TENANT_ID,
            "allowed": json.dumps([str(contact_id)]),
        },
    )
    await session.commit()


def _dinamo_contract() -> dict:
    return json.loads(
        (FIXTURE_DIR / "dinamo_motos_nl_shadow.json").read_text(encoding="utf-8")
    )


def _inbound(conversation_id: UUID, text_value: str) -> Message:
    return Message(
        id=str(uuid4()),
        conversation_id=str(conversation_id),
        tenant_id=str(DINAMO_TENANT_ID),
        direction=MessageDirection.INBOUND,
        text=text_value,
        sent_at=datetime.now(UTC),
    )


def _required_tool_names(universal_trace: dict) -> set[str]:
    proposed = universal_trace.get("gpt_proposed") or {}
    return {
        str(tool.get("name") or tool.get("tool_name"))
        for tool in proposed.get("required_tools", [])
        if isinstance(tool, dict)
    }


async def _outbox_count(session: AsyncSession) -> int:
    return int(
        (
            await session.execute(
                text("SELECT COUNT(*) FROM outbound_outbox WHERE tenant_id = :tenant_id"),
                {"tenant_id": DINAMO_TENANT_ID},
            )
        ).scalar_one()
    )
