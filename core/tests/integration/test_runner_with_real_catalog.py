"""T21 — E2E: runner with real catalog row produces Quote in composer_input.

This is the end-to-end sanity check that Phase 3c.1's wiring actually
delivers real price data into the Composer prompt. We bypass the webhook
HTTP layer (other integration tests already exercise that) and exercise
the runner directly with:

  * A tenant + pipeline + tenant_branding seeded fresh per test
  * 1 real catalog row (Adventure 150 CC, alias=["adventure"]) inserted via
    SQLAlchemy ORM so the halfvec column round-trips cleanly
  * A fake NLU that returns intent=ask_price + interes_producto=Adventure
  * A fake Composer that records the ComposerInput and returns canned text

The assertion is that `composer_input.action_payload` has:
  status='ok', price_contado_mxn='29900', name='Adventure 150 CC'

— i.e. the runner did the alias-keyword lookup, fetched the SKU, called
the real `quote()` against tenant_catalogs, and forwarded the result.
The test runs without OpenAI calls (no embedding cost).
"""

import asyncio
import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from atendia.config import get_settings
from atendia.contracts.message import Message
from atendia.contracts.nlu_result import Intent, NLUResult, Sentiment
from atendia.contracts.pipeline_definition import FieldSpec
from atendia.db.models import TenantCatalogItem
from atendia.runner.composer_protocol import (
    ComposerInput,
    ComposerOutput,
    ComposerProvider,
)
from atendia.runner.conversation_runner import ConversationRunner
from atendia.runner.nlu_protocol import NLUProvider, UsageMetadata

_PIPELINE = {
    "version": 1,
    "stages": [
        {
            "id": "greeting",
            "actions_allowed": ["greet", "ask_field"],
            "transitions": [
                {"to": "qualify", "when": "intent in [ask_info, ask_price]"},
            ],
        },
        {
            "id": "qualify",
            "required_fields": [
                {"name": "interes_producto", "description": "modelo de moto"},
            ],
            "actions_allowed": ["ask_field", "quote", "ask_clarification"],
            "transitions": [
                {"to": "quote", "when": "all_required_fields_present"},
            ],
        },
        {
            "id": "quote",
            "actions_allowed": ["quote", "ask_clarification", "close"],
            "transitions": [],
        },
    ],
    "tone": {"register": "informal_mexicano"},
    "fallback": "escalate_to_human",
    "nlu": {"history_turns": 4},
    "composer": {"history_turns": 4},
}


class _FakeNLU(NLUProvider):
    """Returns a canned NLUResult; ignores history."""

    def __init__(self, intent: Intent, entities: dict[str, Any]) -> None:
        self._intent = intent
        self._entities = entities

    async def classify(
        self,
        *,
        text: str,
        current_stage: str,
        required_fields: list[FieldSpec],
        optional_fields: list[FieldSpec],
        history: list[tuple[str, str]],
    ) -> tuple[NLUResult, UsageMetadata | None]:
        from atendia.contracts.conversation_state import ExtractedField

        ents = {
            k: ExtractedField(value=v, confidence=0.9, source_turn=0)
            for k, v in self._entities.items()
        }
        return NLUResult(
            intent=self._intent,
            entities=ents,
            sentiment=Sentiment.NEUTRAL,
            confidence=0.9,
            ambiguities=[],
        ), None


class _RecordingComposer(ComposerProvider):
    """Captures the ComposerInput it received; returns canned ComposerOutput."""

    def __init__(self, canned_messages: list[str]) -> None:
        self._messages = canned_messages
        self.last_input: ComposerInput | None = None

    async def compose(
        self,
        *,
        input: ComposerInput,
    ) -> tuple[ComposerOutput, UsageMetadata | None]:
        self.last_input = input
        return ComposerOutput(messages=self._messages), None


@pytest.fixture
def adventure_catalog():
    """Seed Dinamo-shaped tenant + pipeline + branding + Adventure catalog row.

    Yields the tenant_id. Tears everything down on exit (the FK cascade
    on tenants takes care of catalog/branding/pipelines).
    """

    async def _setup() -> UUID:
        engine = create_async_engine(get_settings().database_url)
        SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with SessionLocal() as session:
            tid = (
                await session.execute(
                    text("INSERT INTO tenants (name) VALUES ('test_t21_real_catalog') RETURNING id")
                )
            ).scalar()
            await session.execute(
                text(
                    "INSERT INTO tenant_pipelines (tenant_id, version, definition, active) "
                    "VALUES (:t, 1, CAST(:d AS jsonb), true)"
                ),
                {"t": tid, "d": json.dumps(_PIPELINE)},
            )
            await session.execute(
                text(
                    "INSERT INTO tenant_branding (tenant_id, bot_name, voice, default_messages) "
                    "VALUES (:t, 'Dinamo', CAST(:v AS jsonb), CAST('{}' AS jsonb))"
                ),
                {"t": tid, "v": json.dumps({"register": "informal_mexicano"})},
            )
            session.add(
                TenantCatalogItem(
                    tenant_id=tid,
                    sku="adventure-150-cc",
                    name="Adventure 150 CC",
                    category="Motoneta",
                    attrs={
                        "alias": ["adventure", "elite"],
                        "ficha_tecnica": {"motor_cc": 150},
                        "precio_lista": "31395",
                        "precio_contado": "29900",
                        "planes_credito": {
                            "plan_10": {
                                "enganche": 3140,
                                "pago_quincenal": 1247,
                                "quincenas": 72,
                            },
                        },
                    },
                    active=True,
                )
            )
            # conversation + state row so runner can read them
            cid = uuid4()
            cust_id = (
                await session.execute(
                    text(
                        "INSERT INTO customers (tenant_id, phone_e164) "
                        "VALUES (:t, '+5215555550210') RETURNING id"
                    ),
                    {"t": tid},
                )
            ).scalar()
            await session.execute(
                text(
                    "INSERT INTO conversations (id, tenant_id, customer_id, current_stage) "
                    "VALUES (:cid, :t, :c, 'greeting')"
                ),
                {"cid": cid, "t": tid, "c": cust_id},
            )
            await session.execute(
                text(
                    "INSERT INTO conversation_state (conversation_id, "
                    "extracted_data, total_cost_usd) "
                    "VALUES (:cid, CAST('{}' AS jsonb), 0)"
                ),
                {"cid": cid},
            )
            await session.commit()
        await engine.dispose()
        return tid, cid

    async def _cleanup(tid: UUID) -> None:
        engine = create_async_engine(get_settings().database_url)
        SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with SessionLocal() as session:
            await session.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tid})
            await session.commit()
        await engine.dispose()

    tid, cid = asyncio.run(_setup())
    yield tid, cid
    asyncio.run(_cleanup(tid))


def test_runner_dispatches_real_quote_via_alias(adventure_catalog) -> None:
    """Adventure alias hit → quote() returns Quote → composer_input has real price."""
    tenant_id, conversation_id = adventure_catalog

    async def _run() -> None:
        engine = create_async_engine(get_settings().database_url)
        SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        composer = _RecordingComposer(canned_messages=["¡Qué onda! El Adventure cuesta $29,900."])
        async with SessionLocal() as session:
            runner = ConversationRunner(
                session=session,
                nlu_provider=_FakeNLU(
                    intent=Intent.ASK_PRICE,
                    entities={"interes_producto": "Adventure"},
                ),
                composer_provider=composer,
            )
            trace = await runner.run_turn(
                conversation_id=conversation_id,
                tenant_id=tenant_id,
                inbound=Message(
                    id=str(uuid4()),
                    conversation_id=str(conversation_id),
                    tenant_id=str(tenant_id),
                    direction="inbound",
                    text="cuanto cuesta el Adventure?",
                    sent_at=datetime.now(UTC),
                ),
                turn_number=1,
            )
            await session.commit()
        await engine.dispose()
        return composer, trace

    composer, trace = asyncio.run(_run())  # type: ignore[assignment]

    # Composer input was built — proof the runner ran.
    assert composer.last_input is not None, "Composer was never invoked"
    payload = composer.last_input.action_payload

    # The real `quote()` resolved Adventure → adventure-150-cc and returned
    # status='ok' with the seeded prices. NO ToolNoDataResult.
    assert payload.get("status") == "ok", f"Expected status='ok' from real quote(), got: {payload}"
    assert payload.get("name") == "Adventure 150 CC"
    assert payload.get("price_contado_mxn") == "29900"
    assert payload.get("price_lista_mxn") == "31395"
    assert payload.get("planes_credito", {}).get("plan_10", {}).get("enganche") == 3140

    # The ConversationRunner action mapped to "quote" — proof the pipeline
    # transitioned greeting → qualify → quote AND the runner dispatched
    # the right action.
    assert composer.last_input.action == "quote"

    # tool_cost_usd should be NULL (alias path doesn't embed) on this trace.
    assert trace.tool_cost_usd is None or trace.tool_cost_usd == Decimal("0")


def test_runner_dispatches_no_data_for_unknown_model(adventure_catalog) -> None:
    """Unknown alias → search_catalog yields nothing → ToolNoDataResult."""
    tenant_id, conversation_id = adventure_catalog

    async def _run() -> None:
        engine = create_async_engine(get_settings().database_url)
        SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        composer = _RecordingComposer(canned_messages=["Déjame revisar ese modelo."])
        async with SessionLocal() as session:
            runner = ConversationRunner(
                session=session,
                nlu_provider=_FakeNLU(
                    intent=Intent.ASK_PRICE,
                    entities={"interes_producto": "Lambretta 200"},
                ),
                composer_provider=composer,
            )
            await runner.run_turn(
                conversation_id=conversation_id,
                tenant_id=tenant_id,
                inbound=Message(
                    id=str(uuid4()),
                    conversation_id=str(conversation_id),
                    tenant_id=str(tenant_id),
                    direction="inbound",
                    text="cuanto cuesta la Lambretta 200?",
                    sent_at=datetime.now(UTC),
                ),
                turn_number=1,
            )
            await session.commit()
        await engine.dispose()
        return composer

    composer = asyncio.run(_run())
    assert composer.last_input is not None
    payload = composer.last_input.action_payload
    assert payload.get("status") == "no_data"
    assert "lambretta" in payload.get("hint", "").lower()
