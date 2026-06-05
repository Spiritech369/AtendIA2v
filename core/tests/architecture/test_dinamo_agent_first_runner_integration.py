from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select

from atendia.contracts.conversation_state import ExtractedField
from atendia.contracts.message import Message, MessageDirection
from atendia.contracts.nlu_result import Intent, NLUResult, Sentiment
from atendia.db.models import (
    Conversation,
    ConversationStateRow,
    Customer,
    MessageRow,
    OutboundOutbox,
    Tenant,
    TenantPipeline,
    TurnTrace,
)
from atendia.db.session import _get_factory
from atendia.runner import conversation_runner as runner_module
from atendia.runner.composer_protocol import ComposerOutput
from atendia.runner.conversation_runner import ConversationRunner
from atendia.runner.dinamo_agent_runtime import dinamo_runtime_path
from atendia.runner.nlu_protocol import UsageMetadata


class _NoAgentRunner(ConversationRunner):
    async def _load_agent(self, *, conversation_id, tenant_id):
        return None


class _PermissiveNLU:
    async def classify(self, **kwargs):
        return (
            NLUResult(
                intent=Intent.GREETING,
                entities={},
                sentiment=Sentiment.NEUTRAL,
                confidence=0.9,
            ),
            UsageMetadata(
                model="pytest-nlu",
                tokens_in=1,
                tokens_out=1,
                cost_usd=Decimal("0"),
                latency_ms=1,
            ),
        )


class _SpyComposer:
    def __init__(self) -> None:
        self.calls = 0

    async def compose(self, *, input):
        self.calls += 1
        return (
            ComposerOutput(messages=["legacy composer visible text"]),
            UsageMetadata(
                model="pytest-composer",
                tokens_in=1,
                tokens_out=1,
                cost_usd=Decimal("0"),
                latency_ms=1,
            ),
        )


class _FakeToolDispatch:
    def __init__(self, *args, **kwargs) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def lookup_faq(self, **kwargs):
        self.calls.append(("lookup_faq", kwargs))
        return SimpleNamespace(
            action_payload={
                "status": "ok",
                "topic": "ubicacion",
                "answer": "Estamos en Benito Juarez 801, Centro Monterrey.",
            }
        )

    async def search_catalog(self, **kwargs):
        self.calls.append(("search_catalog", kwargs))
        return SimpleNamespace(
            action_payload={
                "status": "ok",
                "results": [{"name": "Adventure Elite 150 CC", "sku": "ADV-150"}],
            }
        )

    async def quote(self, **kwargs):
        self.calls.append(("quote", kwargs))
        return SimpleNamespace(
            action_payload={
                "status": "ok",
                "name": (kwargs.get("candidate_queries") or ["Adventure Elite 150 CC"])[0],
                "cash_price_mxn": 48000,
                "requested_plan_code": kwargs.get("plan_code") or "20%",
                "payment_options": {
                    "20%": {
                        "down_payment_mxn": 9600,
                        "installment_mxn": 1250,
                        "term_count": 48,
                    }
                },
            }
        )


@pytest.mark.asyncio
async def test_dinamo_flag_routes_to_agent_first(monkeypatch):
    monkeypatch.setattr(runner_module, "ToolDispatch", _FakeToolDispatch)
    async with _fixture_session() as session:
        tenant_id, customer_id, conversation_id = await _seed_fixture(session)
        composer = _SpyComposer()
        runner = _NoAgentRunner(session, _PermissiveNLU(), composer)

        trace = await _run_turn(
            runner=runner,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            text="hola, quiero una moto y tambien la ubicacion",
        )

        assert trace.state_after["runtime_path"] == "dinamo_agent_first"
        assert trace.state_after["reason_selected"] == "dinamo_flag_on_sandbox_canary"
        assert composer.calls == 0


@pytest.mark.asyncio
async def test_non_dinamo_stays_on_conversation_runner(monkeypatch):
    monkeypatch.setattr(runner_module, "ToolDispatch", _FakeToolDispatch)
    async with _fixture_session() as session:
        tenant_id, _customer_id, conversation_id = await _seed_fixture(
            session,
            tenant_name="Other Dealer",
        )
        composer = _SpyComposer()
        runner = _NoAgentRunner(session, _PermissiveNLU(), composer)

        trace = await _run_turn(
            runner=runner,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            text="hola",
        )

        assert trace.state_after.get("runtime_path") != "dinamo_agent_first"
        assert composer.calls >= 1


@pytest.mark.asyncio
async def test_dinamo_flag_off_stays_legacy(monkeypatch):
    monkeypatch.setattr(runner_module, "ToolDispatch", _FakeToolDispatch)
    async with _fixture_session() as session:
        tenant_id, _customer_id, conversation_id = await _seed_fixture(
            session,
            feature_enabled=False,
        )
        composer = _SpyComposer()
        runner = _NoAgentRunner(session, _PermissiveNLU(), composer)

        trace = await _run_turn(
            runner=runner,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            text="hola",
        )

        assert trace.state_after.get("runtime_path") != "dinamo_agent_first"
        assert composer.calls >= 1
        assert dinamo_runtime_path(
            {"id": str(tenant_id), "name": "Dinamo Motos NL"},
            {"features": {"dinamo_agent_first": False}},
            customer_attrs={"channel": "api_sandbox_real_path"},
        ) == "conversation_runner"


@pytest.mark.asyncio
async def test_agent_first_persists_final_text_to_trace(monkeypatch):
    monkeypatch.setattr(runner_module, "ToolDispatch", _FakeToolDispatch)
    async with _fixture_session() as session:
        tenant_id, _customer_id, conversation_id = await _seed_fixture(session)
        trace = await _run_agent_first(session, tenant_id, conversation_id, "Donde estan?")

        assert trace.outbound_messages == [trace.state_after["final_text"]]
        assert trace.state_after["final_text_source"] == "agent_final_response"
        assert trace.state_after["final_text"] == "Estamos en Benito Juarez 801, Centro Monterrey."


@pytest.mark.asyncio
async def test_agent_first_does_not_call_legacy_visible_renderers(monkeypatch):
    monkeypatch.setattr(runner_module, "ToolDispatch", _FakeToolDispatch)
    async with _fixture_session() as session:
        tenant_id, _customer_id, conversation_id = await _seed_fixture(session)
        composer = _SpyComposer()
        runner = _NoAgentRunner(session, _PermissiveNLU(), composer)

        trace = await _run_turn(
            runner=runner,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            text="Donde estan?",
        )

        assert composer.calls == 0
        assert trace.state_after["no_legacy_composer_used_for_visible_text"] is True
        assert trace.state_after["no_response_contract_visible_override"] is True
        assert trace.state_after["no_search_catalog_visible_override"] is True
        assert trace.composer_output == {
            "messages": [trace.state_after["final_text"]],
            "source": "agent_final_response",
        }


@pytest.mark.asyncio
async def test_agent_first_blocks_real_outbox_in_canary(monkeypatch):
    monkeypatch.setattr(runner_module, "ToolDispatch", _FakeToolDispatch)
    async with _fixture_session() as session:
        tenant_id, _customer_id, conversation_id = await _seed_fixture(
            session,
            channel="whatsapp_meta",
            customer_attrs={"channel": "whatsapp_meta", "test_run": ""},
        )
        before_outbox = len(
            (await session.execute(
                select(OutboundOutbox).where(OutboundOutbox.tenant_id == tenant_id)
            )).scalars().all()
        )

        trace = await _run_agent_first(
            session,
            tenant_id,
            conversation_id,
            "Donde estan?",
            metadata={},
            to_phone_e164="+528100000000",
        )

        assert "real_outbox_blocked_for_canary" in trace.state_after["safety_flags"]
        outbox_count = len(
            (await session.execute(
                select(OutboundOutbox).where(OutboundOutbox.tenant_id == tenant_id)
            )).scalars().all()
        )
        outbound_messages = (
            await session.execute(
                select(MessageRow).where(
                    MessageRow.conversation_id == conversation_id,
                    MessageRow.direction == "outbound",
                )
            )
        ).scalars().all()
        assert outbox_count == before_outbox
        assert outbound_messages == []


@pytest.mark.asyncio
async def test_agent_first_location_flow_real_runner(monkeypatch):
    monkeypatch.setattr(runner_module, "ToolDispatch", _FakeToolDispatch)
    async with _fixture_session() as session:
        tenant_id, _customer_id, conversation_id = await _seed_fixture(session)
        trace = await _run_agent_first(
            session,
            tenant_id,
            conversation_id,
            "hola, quiero una moto y tambien la ubicacion",
        )

        assert "Benito Juarez" in trace.state_after["final_text"]
        assert trace.state_after["current_question_answered"] is True


@pytest.mark.asyncio
async def test_agent_first_no_doc_incompleta_without_attachment(monkeypatch):
    monkeypatch.setattr(runner_module, "ToolDispatch", _FakeToolDispatch)
    async with _fixture_session() as session:
        tenant_id, _customer_id, conversation_id = await _seed_fixture(session)
        trace = await _run_agent_first(session, tenant_id, conversation_id, "Ya te mande la ine")

        assert trace.state_after["stage_update"] is None
        assert trace.state_after["current_stage"] == "greeting"
        assert "doc_incompleta_blocked_without_attachment" in trace.state_after["safety_flags"]


@pytest.mark.asyncio
async def test_agent_first_no_internal_language_visible(monkeypatch):
    monkeypatch.setattr(runner_module, "ToolDispatch", _FakeToolDispatch)
    async with _fixture_session() as session:
        tenant_id, _customer_id, conversation_id = await _seed_fixture(session)
        trace = await _run_agent_first(session, tenant_id, conversation_id, "Me depositan en tarjeta")

        final_text = trace.state_after["final_text"]
        assert not re.search(r"\b(MOTO|CREDITO|FILTRO|ENGANCHE)\b", final_text)
        assert "registrado" not in final_text.casefold()
        assert "corregirlo" not in final_text.casefold()


@pytest.mark.asyncio
async def test_agent_first_state_write_rejects_income_as_moto(monkeypatch):
    monkeypatch.setattr(runner_module, "ToolDispatch", _FakeToolDispatch)
    async with _fixture_session() as session:
        tenant_id, _customer_id, conversation_id = await _seed_fixture(session)
        trace = await _run_agent_first(session, tenant_id, conversation_id, "Me depositan en tarjeta")

        extracted = trace.state_after["extracted_data"]
        assert "MOTO" not in extracted
        assert "CREDITO" not in extracted


class _fixture_session:
    async def __aenter__(self):
        self.session = _get_factory()()
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        await self.session.rollback()
        await self.session.close()


async def _seed_fixture(
    session,
    *,
    tenant_name: str = "Dinamo Motos NL",
    feature_enabled: bool = True,
    channel: str = "api_sandbox_real_path",
    customer_attrs: dict | None = None,
):
    tenant_id = uuid4()
    customer_id = uuid4()
    conversation_id = uuid4()
    attrs = {
        "channel": channel,
        "test_run": "dinamo_agent_first_canary_pytest",
        **(customer_attrs or {}),
    }
    tenant_config = {
        "features": {"dinamo_agent_first": feature_enabled},
        "brand_facts": {
            "address": "Benito Juarez 801, Centro Monterrey",
            "buro_max_amount": "$50 mil",
        },
    }
    existing_tenant = (
        await session.execute(select(Tenant).where(Tenant.name == tenant_name))
    ).scalar_one_or_none()
    if existing_tenant is not None:
        tenant_id = existing_tenant.id
        existing_tenant.config = tenant_config
        existing_tenant.status = "active"
        session.add(existing_tenant)
    else:
        session.add(
            Tenant(
                id=tenant_id,
                name=tenant_name,
                status="active",
                config=tenant_config,
            )
        )
    await session.flush()
    session.add(
        Customer(
            id=customer_id,
            tenant_id=tenant_id,
            phone_e164=f"+5281{str(tenant_id.int)[-8:]}",
            name="Pytest Dinamo",
            attrs=attrs,
            tags=[],
        )
    )
    await session.flush()
    session.add(
        Conversation(
            id=conversation_id,
            tenant_id=tenant_id,
            customer_id=customer_id,
            channel=channel,
            current_stage="greeting",
            status="active",
        )
    )
    session.add(
        ConversationStateRow(
            conversation_id=conversation_id,
            extracted_data={},
            last_intent=None,
            pending_confirmation=None,
            followups_sent_count=0,
            total_cost_usd=Decimal("0"),
        )
    )
    session.add(
        TenantPipeline(
            tenant_id=tenant_id,
            version=900000 + (uuid4().int % 100000),
            active=True,
            definition={
                "version": 1,
                "fallback": "ask_clarification",
                "stages": [
                    {
                        "id": "greeting",
                        "label": "Greeting",
                        "required_fields": [],
                        "optional_fields": [],
                        "actions_allowed": ["greet", "ask_field", "lookup_faq", "quote"],
                    }
                ],
                "document_requirements_field": "CREDITO",
                "document_requirements": {
                    "Sin Comprobantes": ["INE_FRENTE", "INE_ATRAS"],
                },
                "documents_catalog": [
                    {"key": "INE_FRENTE", "label": "INE frente"},
                    {"key": "INE_ATRAS", "label": "INE atras"},
                ],
            },
        )
    )
    await session.flush()
    return tenant_id, customer_id, conversation_id


async def _run_agent_first(session, tenant_id, conversation_id, text, **kwargs) -> TurnTrace:
    runner = _NoAgentRunner(session, _PermissiveNLU(), _SpyComposer())
    return await _run_turn(
        runner=runner,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        text=text,
        **kwargs,
    )


async def _run_turn(
    *,
    runner: ConversationRunner,
    tenant_id,
    conversation_id,
    text: str,
    metadata: dict | None = None,
    to_phone_e164: str | None = None,
) -> TurnTrace:
    inbound_metadata = (
        {"sandbox": True, "test_run": "dinamo_agent_first_canary_pytest"}
        if metadata is None
        else metadata
    )
    inbound = Message(
        id=str(uuid4()),
        conversation_id=str(conversation_id),
        tenant_id=str(tenant_id),
        direction=MessageDirection.INBOUND,
        text=text,
        sent_at=datetime.now(UTC),
        metadata=inbound_metadata,
        attachments=[],
    )
    return await runner.run_turn(
        conversation_id=conversation_id,
        tenant_id=tenant_id,
        inbound=inbound,
        turn_number=1,
        arq_pool=None,
        to_phone_e164=to_phone_e164,
    )
