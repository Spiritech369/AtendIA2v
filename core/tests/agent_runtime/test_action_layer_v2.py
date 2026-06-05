from __future__ import annotations

import asyncio
import json
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from atendia.agent_runtime import ActionRequest, PostTurnActionExecutor, TurnOutput
from atendia.agent_runtime.schemas import CustomerContext, TurnContext
from atendia.config import get_settings
from atendia.contact_memory import ContactMemoryService
from atendia.lifecycle import LifecycleService

pytestmark = pytest.mark.integration_db


def _run(coro):
    return asyncio.run(coro)


async def _with_session(fn):
    engine = create_async_engine(get_settings().database_url)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            return await fn(session)
    finally:
        await engine.dispose()


async def _seed_tenant(session: AsyncSession) -> str:
    tenant_id = uuid4()
    await session.execute(
        text("INSERT INTO tenants (id, name) VALUES (:id, :name)"),
        {"id": tenant_id, "name": f"action_tenant_{uuid4().hex[:8]}"},
    )
    return str(tenant_id)


async def _seed_customer(session: AsyncSession, tenant_id: str) -> str:
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
    return str(customer_id)


async def _seed_conversation(
    session: AsyncSession,
    tenant_id: str,
    *,
    customer_id: str | None = None,
    stage: str = "new",
) -> str:
    conversation_id = uuid4()
    customer_id = customer_id or await _seed_customer(session, tenant_id)
    await session.execute(
        text(
            "INSERT INTO conversations "
            "(id, tenant_id, customer_id, current_stage, status, tags) "
            "VALUES (:id, :tenant_id, :customer_id, :stage, 'active', CAST('[]' AS jsonb))"
        ),
        {
            "id": conversation_id,
            "tenant_id": UUID(tenant_id),
            "customer_id": UUID(customer_id),
            "stage": stage,
        },
    )
    await session.execute(
        text(
            "INSERT INTO conversation_state (conversation_id, extracted_data) "
            "VALUES (:conversation_id, CAST('{}' AS jsonb))"
        ),
        {"conversation_id": conversation_id},
    )
    return str(conversation_id)


async def _seed_field(session: AsyncSession, tenant_id: str, key: str) -> str:
    field_id = uuid4()
    options = {
        "contact_memory": {
            "write_policy": "ai_auto",
            "confidence_threshold": 0.8,
            "evidence_required": True,
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
    return str(field_id)


async def _seed_pipeline(session: AsyncSession, tenant_id: str) -> None:
    definition = {
        "version": 1,
        "stages": [
            {"id": "new", "label": "New", "allowed_transitions": ["qualified"]},
            {"id": "qualified", "label": "Qualified"},
        ],
    }
    await session.execute(
        text(
            "INSERT INTO tenant_pipelines (tenant_id, version, definition, active) "
            "VALUES (:tenant_id, :version, CAST(:definition AS jsonb), true)"
        ),
        {
            "tenant_id": UUID(tenant_id),
            "version": 800000 + uuid4().int % 10000,
            "definition": json.dumps(definition),
        },
    )


async def _conversation_tags(session: AsyncSession, conversation_id: str) -> list[str]:
    return list(
        (
            await session.execute(
                text("SELECT tags FROM conversations WHERE id = :id"),
                {"id": UUID(conversation_id)},
            )
        ).scalar_one()
        or []
    )


async def _conversation_status(session: AsyncSession, conversation_id: str) -> str:
    return str(
        (
            await session.execute(
                text("SELECT status FROM conversations WHERE id = :id"),
                {"id": UUID(conversation_id)},
            )
        ).scalar_one()
    )


async def _field_value(session: AsyncSession, customer_id: str, field_id: str) -> str | None:
    return (
        await session.execute(
            text(
                "SELECT value FROM customer_field_values "
                "WHERE customer_id = :customer_id AND field_definition_id = :field_id"
            ),
            {"customer_id": UUID(customer_id), "field_id": UUID(field_id)},
        )
    ).scalar_one_or_none()


async def _action_logs(session: AsyncSession, conversation_id: str) -> list[tuple[str, str, bool]]:
    rows = (
        await session.execute(
            text(
                "SELECT action_id, status, dry_run FROM action_execution_logs "
                "WHERE conversation_id = :conversation_id ORDER BY created_at"
            ),
            {"conversation_id": UUID(conversation_id)},
        )
    ).all()
    return [(str(row[0]), str(row[1]), bool(row[2])) for row in rows]


def _context(tenant_id: str, conversation_id: str, customer_id: str | None = None) -> TurnContext:
    return TurnContext(
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        inbound_text="test",
        customer=CustomerContext(id=customer_id),
    )


def test_dry_run_action_does_not_modify_data_and_is_logged():
    async def scenario(session: AsyncSession):
        tenant_id = await _seed_tenant(session)
        conversation_id = await _seed_conversation(session, tenant_id)
        output = TurnOutput(
            final_message="Listo.",
            confidence=0.9,
            actions=[ActionRequest(name="add_tag", payload={"tag": "vip"})],
        )
        results = await PostTurnActionExecutor(session=session).execute(
            output,
            context=_context(tenant_id, conversation_id),
        )
        await session.commit()
        assert results[0].status == "skipped"
        assert await _conversation_tags(session, conversation_id) == []
        assert await _action_logs(session, conversation_id) == [("add_tag", "skipped", True)]

    _run(_with_session(scenario))


def test_unknown_action_fails_and_is_logged():
    async def scenario(session: AsyncSession):
        tenant_id = await _seed_tenant(session)
        conversation_id = await _seed_conversation(session, tenant_id)
        output = TurnOutput(
            final_message="Listo.",
            confidence=0.9,
            actions=[ActionRequest(name="invent_action")],
        )
        results = await PostTurnActionExecutor(session=session).execute(
            output,
            context=_context(tenant_id, conversation_id),
        )
        await session.commit()
        assert results[0].status == "failed"
        assert await _action_logs(session, conversation_id) == [("invent_action", "failed", True)]

    _run(_with_session(scenario))


def test_update_contact_field_action_applies_contact_memory_policy():
    async def scenario(session: AsyncSession):
        tenant_id = await _seed_tenant(session)
        customer_id = await _seed_customer(session, tenant_id)
        conversation_id = await _seed_conversation(
            session,
            tenant_id,
            customer_id=customer_id,
        )
        field_id = await _seed_field(session, tenant_id, "email")
        output = TurnOutput(
            final_message="Gracias.",
            confidence=0.93,
            actions=[
                ActionRequest(
                    name="update_contact_field",
                    payload={"field_key": "email", "value": "ana@example.test", "confidence": 0.93},
                    reason="Customer provided email.",
                    evidence=["ana@example.test"],
                )
            ],
        )
        results = await PostTurnActionExecutor(
            session=session,
            dry_run=False,
            contact_memory_service=ContactMemoryService(session),
            require_runtime_enabled=False,
        ).execute(output, context=_context(tenant_id, conversation_id, customer_id))
        await session.commit()
        assert results[0].status == "succeeded"
        assert await _field_value(session, customer_id, field_id) == "ana@example.test"

    _run(_with_session(scenario))


def test_move_lifecycle_action_requires_reason_in_handler():
    async def scenario(session: AsyncSession):
        tenant_id = await _seed_tenant(session)
        await _seed_pipeline(session, tenant_id)
        conversation_id = await _seed_conversation(session, tenant_id)
        output = TurnOutput(
            final_message="Listo.",
            confidence=0.9,
            actions=[
                ActionRequest(
                    name="move_lifecycle",
                    payload={"target_stage": "qualified"},
                    evidence=["Customer meets criteria."],
                )
            ],
        )
        results = await PostTurnActionExecutor(
            session=session,
            dry_run=False,
            lifecycle_service=LifecycleService(session),
            require_runtime_enabled=False,
        ).execute(output, context=_context(tenant_id, conversation_id))
        await session.commit()
        assert results[0].status == "failed"
        assert "reason" in str(results[0].error)
        assert ("move_lifecycle", "failed", False) in await _action_logs(session, conversation_id)

    _run(_with_session(scenario))


def test_action_tenant_isolation_blocks_wrong_conversation():
    async def scenario(session: AsyncSession):
        tenant_id = await _seed_tenant(session)
        other_tenant_id = await _seed_tenant(session)
        conversation_id = await _seed_conversation(session, other_tenant_id)
        output = TurnOutput(
            final_message="Listo.",
            confidence=0.9,
            actions=[ActionRequest(name="add_tag", payload={"tag": "vip"})],
        )
        results = await PostTurnActionExecutor(
            session=session,
            dry_run=False,
            require_runtime_enabled=False,
        ).execute(output, context=_context(tenant_id, conversation_id))
        await session.commit()
        assert results[0].status == "failed"
        assert await _conversation_tags(session, conversation_id) == []

    _run(_with_session(scenario))


def test_sensitive_action_without_evidence_is_blocked():
    async def scenario(session: AsyncSession):
        tenant_id = await _seed_tenant(session)
        conversation_id = await _seed_conversation(session, tenant_id)
        output = TurnOutput(
            final_message="Listo.",
            confidence=0.9,
            actions=[
                ActionRequest(
                    name="close_conversation",
                    payload={"status": "closed"},
                    reason="Agent thinks conversation is done.",
                )
            ],
        )
        results = await PostTurnActionExecutor(
            session=session,
            dry_run=False,
            require_runtime_enabled=False,
        ).execute(output, context=_context(tenant_id, conversation_id))
        await session.commit()
        assert results[0].status == "failed"
        assert results[0].trace_metadata["policy_blocked"] is True
        assert await _conversation_status(session, conversation_id) == "active"

    _run(_with_session(scenario))


def test_max_actions_per_turn_limits_execution():
    async def scenario(session: AsyncSession):
        tenant_id = await _seed_tenant(session)
        conversation_id = await _seed_conversation(session, tenant_id)
        output = TurnOutput(
            final_message="Listo.",
            confidence=0.9,
            actions=[
                ActionRequest(name="add_tag", payload={"tag": "first"}),
                ActionRequest(name="add_tag", payload={"tag": "second"}),
            ],
        )
        results = await PostTurnActionExecutor(
            session=session,
            dry_run=False,
            max_actions_per_turn=1,
            require_runtime_enabled=False,
        ).execute(output, context=_context(tenant_id, conversation_id))
        await session.commit()
        assert [result.status for result in results] == ["succeeded", "failed"]
        assert await _conversation_tags(session, conversation_id) == ["first"]

    _run(_with_session(scenario))


def test_action_errors_are_logged_without_visible_copy():
    async def scenario(session: AsyncSession):
        tenant_id = await _seed_tenant(session)
        conversation_id = await _seed_conversation(session, tenant_id)
        output = TurnOutput(
            final_message="Listo.",
            confidence=0.9,
            actions=[
                ActionRequest(
                    name="assign_conversation",
                    payload={"user_id": str(uuid4())},
                    reason="Assign to operator.",
                    evidence=["Operator requested."],
                )
            ],
        )
        results = await PostTurnActionExecutor(
            session=session,
            dry_run=False,
            require_runtime_enabled=False,
        ).execute(output, context=_context(tenant_id, conversation_id))
        await session.commit()
        assert results[0].status == "failed"
        assert "final_message" not in results[0].data
        assert await _action_logs(session, conversation_id) == [
            ("assign_conversation", "failed", False)
        ]

    _run(_with_session(scenario))
