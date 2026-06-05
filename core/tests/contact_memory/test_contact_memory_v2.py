from __future__ import annotations

import asyncio
import json
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from atendia.agent_runtime import FieldUpdate, PostTurnActionExecutor, TurnOutput
from atendia.agent_runtime.schemas import CustomerContext, TurnContext
from atendia.config import get_settings
from atendia.contact_memory import ContactMemoryService, ContactMemoryWriteRequest


def _run(coro):
    return asyncio.run(coro)


async def _with_session(fn):
    engine = create_async_engine(get_settings().database_url)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            return await fn(session)
    finally:
        await engine.dispose()


async def _seed_customer(session: AsyncSession, tenant_id: str) -> UUID:
    customer_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO customers (id, tenant_id, phone_e164, attrs) "
            "VALUES (:id, :tenant_id, :phone, CAST('{}' AS jsonb))"
        ),
        {
            "id": customer_id,
            "tenant_id": UUID(tenant_id),
            "phone": f"+52{uuid4().int % 10_000_000_000:010d}",
        },
    )
    return customer_id


async def _seed_tenant(session: AsyncSession) -> str:
    tenant_id = uuid4()
    await session.execute(
        text("INSERT INTO tenants (id, name) VALUES (:id, :name)"),
        {"id": tenant_id, "name": f"cm_tenant_{uuid4().hex[:8]}"},
    )
    return str(tenant_id)


async def _seed_field(
    session: AsyncSession,
    tenant_id: str,
    *,
    key: str,
    write_policy: str = "ai_auto",
    confidence_threshold: float = 0.8,
    evidence_required: bool = True,
) -> UUID:
    field_id = uuid4()
    options = {
        "contact_memory": {
            "write_policy": write_policy,
            "confidence_threshold": confidence_threshold,
            "evidence_required": evidence_required,
            "extractable_by_ai": True,
        }
    }
    await session.execute(
        text(
            "INSERT INTO customer_field_definitions "
            "(id, tenant_id, key, label, field_type, field_options, ordering) "
            "VALUES (:id, :tenant_id, :key, :label, 'text', CAST(:options AS jsonb), 0)"
        ),
        {
            "id": field_id,
            "tenant_id": UUID(tenant_id),
            "key": key,
            "label": key.title(),
            "options": json.dumps(options),
        },
    )
    return field_id


async def _field_value(session: AsyncSession, customer_id: UUID, field_id: UUID) -> str | None:
    return (
        await session.execute(
            text(
                "SELECT value FROM customer_field_values "
                "WHERE customer_id = :customer_id AND field_definition_id = :field_id"
            ),
            {"customer_id": customer_id, "field_id": field_id},
        )
    ).scalar_one_or_none()


async def _evidence_status(session: AsyncSession, customer_id: UUID, key: str) -> str | None:
    return (
        await session.execute(
            text(
                "SELECT status FROM customer_field_update_evidence "
                "WHERE customer_id = :customer_id AND field_key = :key "
                "ORDER BY created_at DESC LIMIT 1"
            ),
            {"customer_id": customer_id, "key": key},
        )
    ).scalar_one_or_none()


async def _suggestion_count(session: AsyncSession, customer_id: UUID, key: str) -> int:
    return int(
        (
            await session.execute(
                text(
                    "SELECT count(*) FROM field_suggestions "
                    "WHERE customer_id = :customer_id AND key = :key"
                ),
                {"customer_id": customer_id, "key": key},
            )
        ).scalar_one()
        or 0
    )


def test_auto_write_with_confidence_and_evidence():
    async def scenario(session: AsyncSession):
        tenant_id = await _seed_tenant(session)
        customer_id = await _seed_customer(session, tenant_id)
        field_id = await _seed_field(session, tenant_id, key="preferred_channel")
        decision = await ContactMemoryService(session).apply_update(
            ContactMemoryWriteRequest(
                tenant_id=UUID(tenant_id),
                customer_id=customer_id,
                field_key="preferred_channel",
                new_value="whatsapp",
                reason="Customer said WhatsApp is best.",
                evidence=["WhatsApp please"],
                confidence=0.91,
            )
        )
        await session.commit()
        assert decision.status == "auto_applied"
        assert decision.applied is True
        assert await _field_value(session, customer_id, field_id) == "whatsapp"
        assert await _evidence_status(session, customer_id, "preferred_channel") == "auto_applied"

    _run(_with_session(scenario))


def test_suggest_when_policy_is_ai_suggest():
    async def scenario(session: AsyncSession):
        tenant_id = await _seed_tenant(session)
        customer_id = await _seed_customer(session, tenant_id)
        field_id = await _seed_field(
            session,
            tenant_id,
            key="budget_range",
            write_policy="ai_suggest",
        )
        decision = await ContactMemoryService(session).apply_update(
            ContactMemoryWriteRequest(
                tenant_id=UUID(tenant_id),
                customer_id=customer_id,
                field_key="budget_range",
                new_value="medium",
                reason="Customer mentioned a medium budget.",
                evidence=["medium budget"],
                confidence=0.95,
            )
        )
        await session.commit()
        assert decision.status == "suggested"
        assert decision.applied is False
        assert await _field_value(session, customer_id, field_id) is None
        assert await _suggestion_count(session, customer_id, "budget_range") == 1

    _run(_with_session(scenario))


def test_reject_when_human_only():
    async def scenario(session: AsyncSession):
        tenant_id = await _seed_tenant(session)
        customer_id = await _seed_customer(session, tenant_id)
        field_id = await _seed_field(
            session,
            tenant_id,
            key="legal_name",
            write_policy="human_only",
        )
        decision = await ContactMemoryService(session).apply_update(
            ContactMemoryWriteRequest(
                tenant_id=UUID(tenant_id),
                customer_id=customer_id,
                field_key="legal_name",
                new_value="Ana",
                reason="AI inferred name.",
                evidence=["I'm Ana"],
                confidence=0.99,
            )
        )
        await session.commit()
        assert decision.status == "rejected"
        assert await _field_value(session, customer_id, field_id) is None
        assert "human_only" in decision.reason

    _run(_with_session(scenario))


def test_reject_when_evidence_is_missing():
    async def scenario(session: AsyncSession):
        tenant_id = await _seed_tenant(session)
        customer_id = await _seed_customer(session, tenant_id)
        field_id = await _seed_field(session, tenant_id, key="city")
        decision = await ContactMemoryService(session).apply_update(
            ContactMemoryWriteRequest(
                tenant_id=UUID(tenant_id),
                customer_id=customer_id,
                field_key="city",
                new_value="Monterrey",
                confidence=0.95,
            )
        )
        await session.commit()
        assert decision.status == "rejected"
        assert await _field_value(session, customer_id, field_id) is None
        assert "evidence" in decision.reason

    _run(_with_session(scenario))


def test_reject_if_field_does_not_belong_to_tenant():
    async def scenario(session: AsyncSession):
        tenant_id = await _seed_tenant(session)
        customer_id = await _seed_customer(session, tenant_id)
        other_tenant_id = uuid4()
        await session.execute(
            text("INSERT INTO tenants (id, name) VALUES (:id, :name)"),
            {"id": other_tenant_id, "name": f"cm_other_{uuid4().hex[:8]}"},
        )
        await _seed_field(session, str(other_tenant_id), key="private_note")
        decision = await ContactMemoryService(session).apply_update(
            ContactMemoryWriteRequest(
                tenant_id=UUID(tenant_id),
                customer_id=customer_id,
                field_key="private_note",
                new_value="hidden",
                reason="Should not cross tenant.",
                evidence=["hidden"],
                confidence=0.95,
            )
        )
        await session.commit()
        assert decision.status == "rejected"
        assert "not found" in decision.reason
        assert await _evidence_status(session, customer_id, "private_note") == "rejected"

    _run(_with_session(scenario))


def test_no_overwrite_confirmed_value_with_low_confidence():
    async def scenario(session: AsyncSession):
        tenant_id = await _seed_tenant(session)
        customer_id = await _seed_customer(session, tenant_id)
        field_id = await _seed_field(
            session,
            tenant_id,
            key="preferred_time",
            confidence_threshold=0.9,
        )
        await session.execute(
            text(
                "INSERT INTO customer_field_values "
                "(customer_id, field_definition_id, value) "
                "VALUES (:customer_id, :field_id, 'morning')"
            ),
            {"customer_id": customer_id, "field_id": field_id},
        )
        decision = await ContactMemoryService(session).apply_update(
            ContactMemoryWriteRequest(
                tenant_id=UUID(tenant_id),
                customer_id=customer_id,
                field_key="preferred_time",
                new_value="evening",
                reason="Ambiguous customer message.",
                evidence=["later maybe"],
                confidence=0.55,
            )
        )
        await session.commit()
        assert decision.status == "needs_review"
        assert decision.applied is False
        assert await _field_value(session, customer_id, field_id) == "morning"
        assert await _suggestion_count(session, customer_id, "preferred_time") == 1

    _run(_with_session(scenario))


def test_post_turn_executor_can_call_contact_memory_service():
    async def scenario(session: AsyncSession):
        tenant_id = await _seed_tenant(session)
        customer_id = await _seed_customer(session, tenant_id)
        field_id = await _seed_field(session, tenant_id, key="email")
        context = TurnContext(
            tenant_id=tenant_id,
            conversation_id=str(uuid4()),
            inbound_text="email is ana@example.test",
            customer=CustomerContext(id=str(customer_id)),
        )
        output = TurnOutput(
            final_message="Gracias, lo tengo.",
            confidence=0.92,
            field_updates=[
                FieldUpdate(
                    field_key="email",
                    value="ana@example.test",
                    reason="Customer provided email.",
                    evidence=["email is ana@example.test"],
                    confidence=0.92,
                    source="customer_message",
                )
            ],
        )
        results = await PostTurnActionExecutor(
            dry_run=False,
            contact_memory_service=ContactMemoryService(session),
            require_runtime_enabled=False,
        ).execute(output, context=context)
        await session.commit()
        assert results[0].action_name == "contact_memory.field_updates"
        assert results[0].status == "succeeded"
        assert await _field_value(session, customer_id, field_id) == "ana@example.test"

    _run(_with_session(scenario))


def test_dry_run_executor_does_not_write_contact_memory():
    async def scenario(session: AsyncSession):
        tenant_id = await _seed_tenant(session)
        customer_id = await _seed_customer(session, tenant_id)
        field_id = await _seed_field(session, tenant_id, key="nickname")
        context = TurnContext(
            tenant_id=tenant_id,
            conversation_id=str(uuid4()),
            inbound_text="Call me Ana",
            customer=CustomerContext(id=str(customer_id)),
        )
        output = TurnOutput(
            final_message="Perfecto.",
            confidence=0.92,
            field_updates=[
                FieldUpdate(
                    field_key="nickname",
                    value="Ana",
                    reason="Customer provided nickname.",
                    evidence=["Call me Ana"],
                    confidence=0.92,
                )
            ],
        )
        results = await PostTurnActionExecutor(
            dry_run=True,
            contact_memory_service=ContactMemoryService(session),
        ).execute(output, context=context)
        await session.commit()
        assert results == []
        assert await _field_value(session, customer_id, field_id) is None

    _run(_with_session(scenario))
