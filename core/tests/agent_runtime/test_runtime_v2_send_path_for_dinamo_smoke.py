from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from atendia.agent_runtime.advisor_pipeline import AdvisorFirstAgentProvider
from atendia.agent_runtime.context_builder import ContextBuilder
from atendia.agent_runtime.schemas import (
    AdvisorBrainDecision,
    TenantRuntimeConfigContext,
    TurnContext,
    TurnInput,
    TurnOutput,
)
from atendia.agent_runtime.send_policy import (
    evaluate_prepared_send_policy,
    provider_fallback_detected_from_trace,
)
from atendia.agent_runtime.tenant_domain_contract import (
    apply_tenant_domain_contract,
    load_tenant_domain_contract,
)
from atendia.config import get_settings
from atendia.contracts.message import Message, MessageDirection
from atendia.runner import conversation_runner as conversation_runner_module
from atendia.runner.composer_protocol import ComposerInput, ComposerOutput
from atendia.runner.conversation_runner import ConversationRunner

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "tenant_domain_contracts"
DINAMO_TENANT_ID = UUID("6ad78236-1fc9-467a-858d-90d248d57ee5")
DINAMO_AGENT_ID = UUID("c169deec-226d-55b7-bd07-270f339e75a6")


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine(get_settings().database_url)
    session_factory = async_sessionmaker(
        engine, expire_on_commit=False, class_=AsyncSession
    )
    async with session_factory() as session:
        yield session
        await session.rollback()
    await engine.dispose()


class _UnusedNLU:
    async def classify(self, **kwargs):  # pragma: no cover - legacy path must not call this
        raise AssertionError("legacy NLU must not run for runtime v2 tenant")


class _RecordingComposer:
    def __init__(self) -> None:
        self.call_count = 0

    async def compose(
        self,
        *,
        input: ComposerInput,
    ) -> tuple[ComposerOutput, None]:  # pragma: no cover - legacy path must not call this
        self.call_count += 1
        return ComposerOutput(messages=["legacy composer text"]), None


@pytest.mark.integration_db
@pytest.mark.asyncio
async def test_runtime_v2_runner_path_generates_trace_and_blocks_send_when_disabled(
    db_session,
    monkeypatch,
):
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_ENABLED", "true")
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_SEND_ENABLED", "true")
    get_settings.cache_clear()
    contact_id, conversation_id = await _seed_dinamo_runtime_conversation(
        db_session,
        runtime_overrides={
            "send_enabled": False,
            "outbox_enabled": False,
            "single_contact_smoke_enabled": False,
        },
    )
    composer = _RecordingComposer()

    trace = await ConversationRunner(db_session, _UnusedNLU(), composer).run_turn(
        conversation_id=conversation_id,
        tenant_id=DINAMO_TENANT_ID,
        inbound=_inbound(conversation_id, "Hola, quiero info de una moto a credito"),
        turn_number=1,
    )
    await db_session.commit()

    assert contact_id
    assert composer.call_count == 0
    assert trace.router_trigger == "agent_runtime_v2_prepared_send_path"
    assert trace.composer_output["source"] == "TurnOutput.final_message"
    assert trace.composer_output["final_message"]
    assert trace.outbound_messages is None
    assert trace.state_after["agent_runtime_v2_executed"] is True
    assert trace.state_after["send_blocked_by_policy"] is True
    assert "tenant_send_disabled" in trace.state_after["send_decision"]["reasons"]
    assert trace.state_after["universal_turn_trace"] is not None
    assert trace.state_after["mandatory_tool_decisions"] is not None
    assert trace.state_after["state_writer_decisions"] is not None
    assert trace.state_after["business_events"]
    assert trace.state_after["workflow_results"]
    assert trace.state_after["whatsapp_send_attempted"] is False
    assert trace.state_after["outbox_write_attempted"] is False
    assert await _outbox_count(db_session) == 0


@pytest.mark.integration_db
@pytest.mark.asyncio
async def test_runtime_v2_contact_approved_reaches_prepared_send_only(
    db_session,
    monkeypatch,
):
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_ENABLED", "true")
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_SEND_ENABLED", "true")
    get_settings.cache_clear()
    contact_id, conversation_id = await _seed_dinamo_runtime_conversation(
        db_session,
        runtime_overrides={
            "send_enabled": True,
            "outbox_enabled": True,
            "single_contact_smoke_enabled": True,
            "send_scope": "approved_contact_only",
            "allowed_contact_ids": [],
            "allowed_test_phones": ["+5215555550037"],
        },
    )
    await db_session.execute(
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
    await db_session.commit()
    composer = _RecordingComposer()

    trace = await ConversationRunner(db_session, _UnusedNLU(), composer).run_turn(
        conversation_id=conversation_id,
        tenant_id=DINAMO_TENANT_ID,
        inbound=_inbound(conversation_id, "Me interesa la R4"),
        turn_number=1,
    )
    await db_session.commit()

    assert composer.call_count == 0
    assert trace.state_after["send_decision"]["status"] == "prepared"
    assert trace.state_after["send_status"] == "prepared"
    assert trace.state_after["send_decision"]["allowed"] is True
    assert trace.state_after["send_decision"]["dry_run"] is True
    assert trace.outbound_messages is None
    assert trace.state_after["whatsapp_send_attempted"] is False
    assert trace.state_after["outbox_write_attempted"] is False
    assert await _outbox_count(db_session) == 0


@pytest.mark.integration_db
@pytest.mark.asyncio
async def test_runtime_v2_runtime_failure_fails_closed_without_legacy_visible_fallback(
    db_session,
    monkeypatch,
):
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_ENABLED", "true")
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_SEND_ENABLED", "true")
    get_settings.cache_clear()
    _, conversation_id = await _seed_dinamo_runtime_conversation(
        db_session,
        runtime_overrides={
            "send_enabled": True,
            "outbox_enabled": True,
            "single_contact_smoke_enabled": True,
            "send_scope": "approved_contact_only",
            "allowed_test_phones": ["+5215555550037"],
        },
    )
    composer = _RecordingComposer()

    class _FailingRuntime:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def run_turn(self, turn_input):
            del turn_input
            raise RuntimeError("runtime v2 unavailable")

    monkeypatch.setattr(conversation_runner_module, "AgentRuntime", _FailingRuntime)

    trace = await ConversationRunner(db_session, _UnusedNLU(), composer).run_turn(
        conversation_id=conversation_id,
        tenant_id=DINAMO_TENANT_ID,
        inbound=_inbound(conversation_id, "me interesa una moto"),
        turn_number=1,
    )
    await db_session.commit()

    assert composer.call_count == 0
    assert trace.composer_output is None
    assert trace.outbound_messages is None
    assert trace.state_after["send_status"] == "no_send"
    assert trace.state_after["send_reason"] == "runtime_v2_failed_closed"
    assert trace.state_after["internal_event"] == "runtime_v2_no_send"
    assert trace.state_after["legacy_fallback_used"] is False
    assert trace.state_after["customer_visible_message_sent"] is False
    assert trace.state_after["legacy_visible_output_blocked"]["event"] == (
        "legacy_visible_output_blocked"
    )
    assert trace.bot_paused is True
    assert await _outbox_count(db_session) == 0


@pytest.mark.integration_db
@pytest.mark.asyncio
async def test_runtime_v2_provider_fallback_is_no_send_without_intermitencia_text(
    db_session,
    monkeypatch,
):
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_ENABLED", "true")
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_SEND_ENABLED", "true")
    get_settings.cache_clear()
    contact_id, conversation_id = await _seed_dinamo_runtime_conversation(
        db_session,
        runtime_overrides={
            "send_enabled": True,
            "outbox_enabled": True,
            "single_contact_smoke_enabled": True,
            "send_scope": "approved_contact_only",
            "allowed_contact_ids": [],
            "allowed_test_phones": ["+5215555550037"],
        },
    )
    await db_session.execute(
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
        {"tenant_id": DINAMO_TENANT_ID, "allowed": json.dumps([str(contact_id)])},
    )
    await db_session.commit()

    class _ProviderFallbackRuntime:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def run_turn(self, turn_input):
            del turn_input
            return TurnOutput(
                final_message="Recibi tu mensaje con intermitencia.",
                confidence=0.0,
                needs_human=True,
                trace_metadata={
                    "fallback": "safe_advisor_brain",
                    "human_review_notes": ["advisor_brain_provider_error"],
                },
            )

    monkeypatch.setattr(conversation_runner_module, "AgentRuntime", _ProviderFallbackRuntime)
    composer = _RecordingComposer()

    trace = await ConversationRunner(db_session, _UnusedNLU(), composer).run_turn(
        conversation_id=conversation_id,
        tenant_id=DINAMO_TENANT_ID,
        inbound=_inbound(conversation_id, "puedes cotizar?"),
        turn_number=1,
    )
    await db_session.commit()

    assert composer.call_count == 0
    assert trace.outbound_messages is None
    assert trace.state_after["send_status"] == "no_send"
    assert trace.state_after["internal_event"] == "provider_failure_needs_review"
    assert trace.state_after["provider_error"] is True
    assert trace.state_after["customer_visible_message_sent"] is False
    assert trace.state_after["send_decision"]["provider_fallback_blocked"] is True
    assert await _outbox_count(db_session) == 0


@pytest.mark.integration_db
@pytest.mark.asyncio
async def test_runtime_v2_unapproved_contact_blocks_send_without_legacy_fallback(
    db_session,
    monkeypatch,
):
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_ENABLED", "true")
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_SEND_ENABLED", "true")
    get_settings.cache_clear()
    _, conversation_id = await _seed_dinamo_runtime_conversation(
        db_session,
        runtime_overrides={
            "send_enabled": True,
            "outbox_enabled": True,
            "single_contact_smoke_enabled": True,
            "send_scope": "approved_contact_only",
            "allowed_contact_ids": ["00000000-0000-0000-0000-000000000000"],
            "allowed_test_phones": ["+5215555550099"],
        },
    )
    composer = _RecordingComposer()

    trace = await ConversationRunner(db_session, _UnusedNLU(), composer).run_turn(
        conversation_id=conversation_id,
        tenant_id=DINAMO_TENANT_ID,
        inbound=_inbound(conversation_id, "Me interesa la R4"),
        turn_number=1,
    )
    await db_session.commit()

    assert composer.call_count == 0
    assert trace.state_after["send_status"] == "blocked_contact_not_allowed"
    assert trace.state_after["send_reason"] == "contact_not_approved_for_single_contact_smoke"
    assert trace.state_after["customer_visible_message_sent"] is False
    assert trace.outbound_messages is None
    assert await _outbox_count(db_session) == 0


@pytest.mark.integration_db
@pytest.mark.asyncio
async def test_runtime_v2_blocks_manual_recovery_docs_visible_path(db_session, monkeypatch):
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_ENABLED", "true")
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_SEND_ENABLED", "true")
    get_settings.cache_clear()
    _, conversation_id = await _seed_dinamo_runtime_conversation(
        db_session,
        runtime_overrides={
            "send_enabled": False,
            "outbox_enabled": False,
            "single_contact_smoke_enabled": False,
        },
    )
    composer = _RecordingComposer()

    trace = await ConversationRunner(db_session, _UnusedNLU(), composer).run_turn(
        conversation_id=conversation_id,
        tenant_id=DINAMO_TENANT_ID,
        inbound=_inbound(conversation_id, "Te mando mi INE para papeleria"),
        turn_number=1,
    )
    await db_session.commit()

    assert composer.call_count == 0
    assert trace.state_after["manual_recovery_visible_blocked"] is True
    assert trace.state_after["legacy_fallback_used"] is False
    assert trace.state_after["customer_visible_message_sent"] is False
    assert trace.outbound_messages is None
    assert await _outbox_count(db_session) == 0


def test_contact_gate_blocks_unapproved_missing_and_multiple_contacts() -> None:
    base = _runtime_config(
        send_enabled=True,
        outbox_enabled=True,
        single_contact_smoke_enabled=True,
        send_scope="approved_contact_only",
    )

    unapproved = evaluate_prepared_send_policy(
        runtime_config={
            **base,
            "allowed_contact_ids": ["approved-contact"],
            "allowed_test_phones": ["+5215555550037"],
        },
        global_send_enabled=True,
        contact_id="other-contact",
        phone_e164="+5215555550099",
    )
    assert unapproved.allowed is False
    assert "contact_not_approved_for_single_contact_smoke" in unapproved.reasons

    missing = evaluate_prepared_send_policy(
        runtime_config=base,
        global_send_enabled=True,
        contact_id="approved-contact",
        phone_e164="+5215555550037",
    )
    assert missing.allowed is False
    assert "approved_contact_allowlist_missing" in missing.reasons

    multiple = evaluate_prepared_send_policy(
        runtime_config={
            **base,
            "allowed_contact_ids": ["contact-1", "contact-2"],
            "allowed_test_phones": ["+5215555550037"],
        },
        global_send_enabled=True,
        contact_id="contact-1",
        phone_e164="+5215555550037",
    )
    assert multiple.allowed is False
    assert "single_contact_smoke_requires_exactly_one_allowed_contact" in multiple.reasons


def test_provider_fallback_blocks_visible_send_policy() -> None:
    trace_metadata = {
        "fallback": "safe_advisor_brain",
        "human_review_notes": ["advisor_brain_provider_error"],
    }
    decision = evaluate_prepared_send_policy(
        runtime_config=_runtime_config(
            send_enabled=True,
            outbox_enabled=True,
            single_contact_smoke_enabled=True,
            send_scope="approved_contact_only",
            allowed_contact_ids=["contact-1"],
            allowed_test_phones=["+5215555550037"],
        ),
        global_send_enabled=True,
        contact_id="contact-1",
        phone_e164="+5215555550037",
        provider_fallback_detected=provider_fallback_detected_from_trace(trace_metadata),
    )

    assert decision.allowed is False
    assert decision.provider_fallback_blocked is True
    assert "provider_fallback_blocks_visible_send" in decision.reasons
    assert decision.whatsapp_send_attempted is False
    assert decision.outbox_write_attempted is False


@pytest.mark.asyncio
async def test_provider_error_turn_output_is_internal_only_and_needs_human() -> None:
    raw_contract = _dinamo_contract()
    config = apply_tenant_domain_contract(
        TenantRuntimeConfigContext(),
        load_tenant_domain_contract(
            raw_contract,
            tenant_id=str(DINAMO_TENANT_ID),
            agent_id=str(DINAMO_AGENT_ID),
        ),
    )
    context = TurnContext(
        tenant_id=str(DINAMO_TENANT_ID),
        conversation_id=str(uuid4()),
        inbound_text="Me puedes cotizar?",
        tenant_config=config,
        metadata={"turn_number": 1},
    )

    output = await AdvisorFirstAgentProvider(advisor_brain=_FailingAdvisorBrain()).generate(
        context
    )
    decision = evaluate_prepared_send_policy(
        runtime_config=_runtime_config(
            send_enabled=True,
            outbox_enabled=True,
            single_contact_smoke_enabled=True,
            send_scope="approved_contact_only",
            allowed_contact_ids=["contact-1"],
            allowed_test_phones=["+5215555550037"],
        ),
        global_send_enabled=True,
        contact_id="contact-1",
        phone_e164="+5215555550037",
        provider_fallback_detected=provider_fallback_detected_from_trace(
            output.trace_metadata
        ),
    )

    assert output.needs_human is True
    assert "universal_turn_trace" in output.trace_metadata
    assert decision.allowed is False
    assert "provider_fallback_blocks_visible_send" in decision.reasons


@pytest.mark.integration_db
@pytest.mark.asyncio
async def test_dinamo_shadow_contract_loads_runtime_context_metadata(db_session):
    await _seed_dinamo_runtime_conversation(db_session, runtime_overrides={})
    context = await ContextBuilder(db_session).build(
        TurnInput(
            tenant_id=str(DINAMO_TENANT_ID),
            conversation_id=str(
                (
                    await db_session.execute(
                        text(
                            "SELECT id FROM conversations WHERE tenant_id = :tenant_id LIMIT 1"
                        ),
                        {"tenant_id": DINAMO_TENANT_ID},
                    )
                ).scalar_one()
            ),
            inbound_text="Hola",
            metadata={"agent_id": str(DINAMO_AGENT_ID)},
        )
    )

    assert context.tenant_config.domain == "vehicle_credit_sales"
    assert context.tenant_config.field_metadata
    assert context.tenant_config.tool_metadata
    assert context.tenant_config.guard_metadata
    assert context.tenant_config.workflow_event_metadata
    assert context.tenant_config.frontend_metadata
    assert context.tenant_config.safe_mode is False


class _FailingAdvisorBrain:
    async def decide(self, context: TurnContext) -> AdvisorBrainDecision:
        del context
        raise RuntimeError("provider unavailable")


async def _seed_dinamo_runtime_conversation(
    session: AsyncSession,
    *,
    runtime_overrides: dict,
) -> tuple[UUID, UUID]:
    raw_contract = _dinamo_contract()
    runtime_config = _runtime_config(
        tenant_domain_contract=raw_contract,
        agent_id=str(DINAMO_AGENT_ID),
        allowed_agent_ids=[str(DINAMO_AGENT_ID)],
        actions_enabled=False,
        workflow_side_effects_enabled=False,
        **runtime_overrides,
    )
    await session.execute(
        text(
            """INSERT INTO tenants (id, name, config)
            VALUES (:id, :name, CAST(:config AS jsonb))"""
        ),
        {
            "id": DINAMO_TENANT_ID,
            "name": "Dinamo Motos NL shadow smoke",
            "config": json.dumps({"agent_runtime_v2": runtime_config}),
        },
    )
    contact_id = (
        await session.execute(
            text(
                """INSERT INTO customers (tenant_id, phone_e164, name)
                VALUES (:tenant_id, '+5215555550037', 'Contacto smoke aprobado')
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
    return {
        "runtime_v2_enabled": True,
        "rollout_mode": "single_contact_smoke",
        "send_enabled": False,
        "outbox_enabled": False,
        "actions_enabled": False,
        "workflow_side_effects_enabled": False,
        "single_contact_smoke_enabled": False,
        **overrides,
    }


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


async def _outbox_count(session: AsyncSession) -> int:
    return int(
        (
            await session.execute(text("SELECT COUNT(*) FROM outbound_outbox"))
        ).scalar_one()
    )
