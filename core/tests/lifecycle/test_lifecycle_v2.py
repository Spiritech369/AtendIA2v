from __future__ import annotations

import asyncio
import json
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from atendia.agent_runtime import (
    ActionRequest,
    LifecycleUpdate,
    PolicyValidationError,
    PolicyValidator,
    PostTurnActionExecutor,
    TurnOutput,
)
from atendia.agent_runtime.schemas import TurnContext
from atendia.config import get_settings
from atendia.lifecycle import LifecycleService, PipelineLifecycleAdapter
from atendia.lifecycle.schemas import LifecycleStageUpdateRequest


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
        {"id": tenant_id, "name": f"lifecycle_tenant_{uuid4().hex[:8]}"},
    )
    return str(tenant_id)


async def _seed_pipeline(session: AsyncSession, tenant_id: str) -> None:
    definition = {
        "version": 1,
        "stages": [
            {
                "id": "new",
                "label": "New",
                "required_fields": [{"name": "email"}],
                "optional_fields": [{"name": "company"}],
                "actions_allowed": ["add_tag", "move_lifecycle"],
                "recommended_actions": ["add_tag"],
                "allowed_transitions": ["qualified"],
                "timeout_hours": 24,
            },
            {
                "id": "qualified",
                "label": "Qualified",
                "actions_allowed": ["assign_conversation"],
                "allowed_transitions": ["closed"],
            },
            {"id": "closed", "label": "Closed", "is_terminal": True},
        ],
    }
    await session.execute(
        text(
            "INSERT INTO tenant_pipelines (tenant_id, version, definition, active) "
            "VALUES (:tenant_id, :version, CAST(:definition AS jsonb), true)"
        ),
        {
            "tenant_id": UUID(tenant_id),
            "version": 700000 + uuid4().int % 10000,
            "definition": json.dumps(definition),
        },
    )


async def _seed_conversation(
    session: AsyncSession,
    tenant_id: str,
    *,
    stage: str = "new",
) -> str:
    customer_id = uuid4()
    conversation_id = uuid4()
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
    await session.execute(
        text(
            "INSERT INTO conversations "
            "(id, tenant_id, customer_id, current_stage, status) "
            "VALUES (:id, :tenant_id, :customer_id, :stage, 'active')"
        ),
        {
            "id": conversation_id,
            "tenant_id": UUID(tenant_id),
            "customer_id": customer_id,
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


async def _current_stage(session: AsyncSession, conversation_id: str) -> str:
    return str(
        (
            await session.execute(
                text("SELECT current_stage FROM conversations WHERE id = :id"),
                {"id": UUID(conversation_id)},
            )
        ).scalar_one()
    )


async def _history_count(session: AsyncSession, conversation_id: str) -> int:
    return int(
        (
            await session.execute(
                text(
                    "SELECT count(*) FROM lifecycle_stage_history "
                    "WHERE conversation_id = :conversation_id"
                ),
                {"conversation_id": UUID(conversation_id)},
            )
        ).scalar_one()
        or 0
    )


def test_pipeline_lifecycle_adapter_reads_legacy_pipeline():
    async def scenario(session: AsyncSession):
        tenant_id = await _seed_tenant(session)
        await _seed_pipeline(session, tenant_id)
        stages = await PipelineLifecycleAdapter(session).list_stages(UUID(tenant_id))
        assert [stage.id for stage in stages] == ["new", "qualified", "closed"]
        assert stages[0].required_fields == ["email"]
        assert stages[0].recommended_fields == ["email", "company"]
        assert stages[0].allowed_actions == ["add_tag", "move_lifecycle"]
        assert stages[0].sla_policy["timeout_hours"] == 24

    _run(_with_session(scenario))


def test_stage_update_valid_applies_and_audits():
    async def scenario(session: AsyncSession):
        tenant_id = await _seed_tenant(session)
        await _seed_pipeline(session, tenant_id)
        conversation_id = await _seed_conversation(session, tenant_id)
        decision = await LifecycleService(session).apply_stage_update(
            LifecycleStageUpdateRequest(
                tenant_id=UUID(tenant_id),
                conversation_id=UUID(conversation_id),
                target_stage="qualified",
                reason="Customer meets criteria.",
                evidence=["Customer provided required information."],
                confidence=0.88,
            )
        )
        await session.commit()
        assert decision.valid is True
        assert decision.applied is True
        assert await _current_stage(session, conversation_id) == "qualified"
        assert await _history_count(session, conversation_id) == 1

    _run(_with_session(scenario))


def test_policy_validator_rejects_lifecycle_without_reason_evidence_confidence():
    output = TurnOutput(
        final_message="Listo.",
        confidence=0.8,
        lifecycle_update=LifecycleUpdate(target_stage="qualified"),
    )

    with pytest.raises(PolicyValidationError) as exc:
        PolicyValidator().validate_or_raise(output)

    text = str(exc.value)
    assert "lifecycle_update_missing_reason" in text
    assert "lifecycle_update_missing_evidence" in text
    assert "lifecycle_update_missing_confidence" in text


def test_stage_update_to_unknown_stage_fails():
    async def scenario(session: AsyncSession):
        tenant_id = await _seed_tenant(session)
        await _seed_pipeline(session, tenant_id)
        conversation_id = await _seed_conversation(session, tenant_id)
        decision = await LifecycleService(session).validate_stage_update(
            LifecycleStageUpdateRequest(
                tenant_id=UUID(tenant_id),
                conversation_id=UUID(conversation_id),
                target_stage="missing",
                reason="Try missing stage.",
                evidence=["test"],
                confidence=0.9,
            )
        )
        assert decision.valid is False
        assert "unknown" in decision.reason

    _run(_with_session(scenario))


def test_lifecycle_tenant_isolation():
    async def scenario(session: AsyncSession):
        tenant_id = await _seed_tenant(session)
        other_tenant_id = await _seed_tenant(session)
        await _seed_pipeline(session, tenant_id)
        await _seed_pipeline(session, other_tenant_id)
        conversation_id = await _seed_conversation(session, other_tenant_id)
        decision = await LifecycleService(session).validate_stage_update(
            LifecycleStageUpdateRequest(
                tenant_id=UUID(tenant_id),
                conversation_id=UUID(conversation_id),
                target_stage="qualified",
                reason="Wrong tenant should not see conversation.",
                evidence=["test"],
                confidence=0.9,
            )
        )
        assert decision.valid is False
        assert "conversation not found" in decision.reason

    _run(_with_session(scenario))


def test_lifecycle_executor_does_not_produce_final_text():
    async def scenario(session: AsyncSession):
        tenant_id = await _seed_tenant(session)
        await _seed_pipeline(session, tenant_id)
        conversation_id = await _seed_conversation(session, tenant_id)
        output = TurnOutput(
            final_message="Ya actualicé la etapa.",
            confidence=0.9,
            lifecycle_update=LifecycleUpdate(
                target_stage="qualified",
                reason="Customer qualified.",
                evidence=["Customer answered qualification questions."],
                confidence=0.9,
            ),
        )
        result = (
            await PostTurnActionExecutor(
                dry_run=False,
                lifecycle_service=LifecycleService(session),
                require_runtime_enabled=False,
            ).execute(
                output,
                context=TurnContext(
                    tenant_id=tenant_id,
                    conversation_id=conversation_id,
                    inbound_text="ok",
                ),
            )
        )[0]
        await session.commit()
        assert result.action_name == "lifecycle.update"
        assert "final_message" not in result.data
        assert await _current_stage(session, conversation_id) == "qualified"

    _run(_with_session(scenario))


def test_move_lifecycle_action_uses_lifecycle_service():
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
                    reason="Action requested lifecycle move.",
                    evidence=["Customer is ready."],
                    metadata={"confidence": 0.93},
                )
            ],
        )
        results = await PostTurnActionExecutor(
            dry_run=False,
            lifecycle_service=LifecycleService(session),
            require_runtime_enabled=False,
        ).execute(
            output,
            context=TurnContext(
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                inbound_text="ready",
            ),
        )
        await session.commit()
        assert results[0].action_name == "move_lifecycle"
        assert results[0].status == "succeeded"
        assert await _current_stage(session, conversation_id) == "qualified"
        assert await _history_count(session, conversation_id) == 1

    _run(_with_session(scenario))


def test_pipeline_legacy_tables_still_work_after_lifecycle_layer():
    async def scenario(session: AsyncSession):
        tenant_id = await _seed_tenant(session)
        await _seed_pipeline(session, tenant_id)
        conversation_id = await _seed_conversation(session, tenant_id)
        before = await _current_stage(session, conversation_id)
        stages = await PipelineLifecycleAdapter(session).list_stages(UUID(tenant_id))
        after = await _current_stage(session, conversation_id)
        assert before == "new"
        assert after == before
        assert stages

    _run(_with_session(scenario))
