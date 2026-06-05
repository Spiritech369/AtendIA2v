from __future__ import annotations

import asyncio
import json
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from atendia.agent_runtime import ActionRequest, FieldUpdate, LifecycleUpdate, TurnOutput
from atendia.config import get_settings
from atendia.simulation.reporting import write_persistent_simulation_report
from atendia.simulation.runner import FIXTURE_PATH, SimulationLabRunner, load_fixture


def _run(coro):
    return asyncio.run(coro)


async def _with_session(fn):
    engine = create_async_engine(get_settings().database_url)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            return await fn(session)
    finally:
        await engine.dispose()


async def _seed_tenant(session: AsyncSession) -> tuple[UUID, UUID]:
    tenant_id = uuid4()
    await session.execute(
        text("INSERT INTO tenants (id, name) VALUES (:id, :name)"),
        {"id": tenant_id, "name": f"sim_tenant_{uuid4().hex[:8]}"},
    )
    source_id = uuid4()
    item_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO knowledge_sources "
            "(id, tenant_id, name, type, content_type, status) "
            "VALUES (:id, :tenant_id, 'Sim KB', 'manual', 'faq', 'active')"
        ),
        {"id": source_id, "tenant_id": tenant_id},
    )
    await session.execute(
        text(
            "INSERT INTO knowledge_items "
            "(id, tenant_id, source_id, title, content, status, active) "
            "VALUES (:id, :tenant_id, :source_id, 'Sim', :content, 'active', true)"
        ),
        {
            "id": item_id,
            "tenant_id": tenant_id,
            "source_id": source_id,
            "content": "credito nomina documentos catalogo buro",
        },
    )
    await session.execute(
        text(
            "INSERT INTO knowledge_os_chunks "
            "(id, tenant_id, source_id, item_id, chunk_text, chunk_index, status) "
            "VALUES (:id, :tenant_id, :source_id, :item_id, :content, 0, 'active')"
        ),
        {
            "id": uuid4(),
            "tenant_id": tenant_id,
            "source_id": source_id,
            "item_id": item_id,
            "content": "credito nomina documentos catalogo buro",
        },
    )
    agent_id = (
        await session.execute(
            text(
                "INSERT INTO agents "
                "(tenant_id, name, role, status, knowledge_config, auto_actions, ops_config) "
                "VALUES (:tenant_id, 'Sim Agent', 'sales', 'production', "
                "CAST(:knowledge AS jsonb), CAST(:actions AS jsonb), CAST(:ops AS jsonb)) "
                "RETURNING id"
            ),
            {
                "tenant_id": tenant_id,
                "knowledge": json.dumps({"enabled_source_ids": [str(source_id)]}),
                "actions": json.dumps({"enabled_action_ids": ["add_tag", "move_lifecycle"]}),
                "ops": json.dumps(
                    {
                        "agent_studio_v2": {
                            "enabled_knowledge_source_ids": [str(source_id)],
                            "enabled_action_ids": ["add_tag", "move_lifecycle"],
                            "visible_contact_field_keys": [
                                "income_type",
                                "CREDITO",
                                "ENGANCHE",
                                "INE_FRENTE",
                                "buro_status",
                            ],
                            "allowed_lifecycle_stage_ids": [
                                "nuevos",
                                "credito",
                                "doc_incompleta",
                            ],
                        }
                    }
                ),
            },
        )
    ).scalar_one()
    stages = {
        "version": 1,
        "stages": [
            {
                "id": "nuevos",
                "label": "Nuevos",
                "allowed_transitions": ["credito", "doc_incompleta"],
            },
            {
                "id": "credito",
                "label": "Credito",
                "allowed_transitions": ["doc_incompleta"],
            },
            {
                "id": "doc_incompleta",
                "label": "Doc incompleta",
                "allowed_transitions": ["credito"],
            },
        ],
    }
    await session.execute(
        text(
            "INSERT INTO tenant_pipelines (tenant_id, version, definition, active) "
            "VALUES (:tenant_id, :version, CAST(:definition AS jsonb), true)"
        ),
        {
            "tenant_id": tenant_id,
            "version": 880000 + uuid4().int % 10000,
            "definition": json.dumps(stages),
        },
    )
    for idx, key in enumerate(["income_type", "CREDITO", "ENGANCHE", "INE_FRENTE", "buro_status"]):
        await session.execute(
            text(
                "INSERT INTO customer_field_definitions "
                "(id, tenant_id, key, label, field_type, field_options, ordering) "
                "VALUES (:id, :tenant_id, :key, :key, 'text', CAST(:options AS jsonb), :idx)"
            ),
            {
                "id": uuid4(),
                "tenant_id": tenant_id,
                "key": key,
                "idx": idx,
                "options": json.dumps(
                    {
                        "contact_memory": {
                            "write_policy": "ai_auto",
                            "confidence_threshold": 0.5,
                            "evidence_required": True,
                        }
                    }
                ),
            },
        )
    await session.commit()
    return tenant_id, agent_id


async def _outbox_count(session: AsyncSession, tenant_id: UUID) -> int:
    return int(
        (
            await session.execute(
                text("SELECT COUNT(*) FROM outbound_outbox WHERE tenant_id = :tenant_id"),
                {"tenant_id": tenant_id},
            )
        ).scalar()
        or 0
    )


def test_fixture_carga_correctamente():
    fixture = load_fixture(FIXTURE_PATH)

    assert fixture.name == "dinamo_order_chaos"
    assert len(fixture.cases) >= 15
    assert fixture.cases[0].turns


def test_dinamo_preparation_fixture_uses_official_fields_and_stages():
    fixture = load_fixture(FIXTURE_PATH.parent / "dinamo_preparation_v1.yaml")
    field_keys = {
        key
        for case in fixture.cases
        for key in case.expected_field_updates
    }
    stage_ids = {
        stage
        for case in fixture.cases
        for stage in case.expected_stage_changes
    }

    assert fixture.name == "dinamo_preparation_v1"
    assert len(fixture.cases) >= 20
    assert {
        "CUMPLE_ANTIGUEDAD",
        "PLAN",
        "MOTO_INTERES",
        "DOCUMENTOS_COMPLETOS",
    }.issubset(field_keys)
    assert {
        "plan",
        "cliente_potencial",
        "papeleria_incompleta",
        "papeleria_completa",
    }.issubset(stage_ids)


def test_simulation_creates_conversation_messages_traces_and_report():
    async def scenario(session: AsyncSession):
        tenant_id, agent_id = await _seed_tenant(session)
        before_outbox = await _outbox_count(session, tenant_id)

        result = await SimulationLabRunner(session).run_fixture(
            tenant_id=tenant_id,
            agent_id=agent_id,
        )
        await session.commit()
        report = write_persistent_simulation_report(result)

        conversation_id = result["cases"][0].conversation_id
        assert conversation_id is not None
        assert result["turns"]
        assert report.exists()
        assert await _outbox_count(session, tenant_id) == before_outbox
        inbound_count = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM messages "
                    "WHERE tenant_id = :tenant_id AND direction = 'inbound' "
                    "AND metadata_json->>'is_simulation' = 'true'"
                ),
                {"tenant_id": tenant_id},
            )
        ).scalar_one()
        outbound_count = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM messages "
                    "WHERE tenant_id = :tenant_id AND direction = 'outbound' "
                    "AND metadata_json->>'is_simulation' = 'true'"
                ),
                {"tenant_id": tenant_id},
            )
        ).scalar_one()
        trace_count = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM turn_traces "
                    "WHERE tenant_id = :tenant_id "
                    "AND router_trigger = 'agent_runtime_v2_simulation'"
                ),
                {"tenant_id": tenant_id},
            )
        ).scalar_one()
        assert inbound_count == len(result["turns"])
        assert outbound_count == len(result["turns"])
        assert trace_count == len(result["turns"])

    _run(_with_session(scenario))


def test_simulation_applies_fields_and_lifecycle_only_to_simulated_entities():
    async def scenario(session: AsyncSession):
        tenant_id, agent_id = await _seed_tenant(session)
        real_customer_id = uuid4()
        await session.execute(
            text(
                "INSERT INTO customers (id, tenant_id, phone_e164, attrs) "
                "VALUES (:id, :tenant_id, :phone, CAST('{}' AS jsonb))"
            ),
            {"id": real_customer_id, "tenant_id": tenant_id, "phone": f"+52{uuid4().hex[:10]}"},
        )
        result = await SimulationLabRunner(session).run_fixture(
            tenant_id=tenant_id,
            agent_id=agent_id,
        )
        await session.commit()
        real_values = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM customer_field_values "
                    "WHERE customer_id = :customer_id"
                ),
                {"customer_id": real_customer_id},
            )
        ).scalar_one()
        simulated_values = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM customer_field_values cfv "
                    "JOIN customers c ON c.id = cfv.customer_id "
                    "WHERE c.tenant_id = :tenant_id "
                    "AND c.attrs->>'is_simulation' = 'true'"
                ),
                {"tenant_id": tenant_id},
            )
        ).scalar_one()
        lifecycle_moves = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM lifecycle_stage_history "
                    "WHERE tenant_id = :tenant_id"
                ),
                {"tenant_id": tenant_id},
            )
        ).scalar_one()
        assert real_values == 0
        assert simulated_values > 0
        assert lifecycle_moves > 0
        assert result["safety_delta"]["real_customers"] == 0

    _run(_with_session(scenario))


class _UnknownActionProvider:
    async def generate(self, context):
        return TurnOutput(
            final_message="Listo.",
            confidence=0.9,
            actions=[ActionRequest(name="unknown_action", evidence=[context.inbound_text])],
        )


class _BadFieldProvider:
    async def generate(self, context):
        return TurnOutput(
            final_message="Listo.",
            confidence=0.9,
            field_updates=[FieldUpdate(field_key="income_type", value="Nomina")],
        )


class _BadLifecycleProvider:
    async def generate(self, context):
        return TurnOutput(
            final_message="Listo.",
            confidence=0.9,
            lifecycle_update=LifecycleUpdate(
                target_stage="missing",
                reason="bad",
                evidence=[context.inbound_text],
                confidence=0.9,
            ),
        )


class _LegacyProvider:
    async def generate(self, context):
        return TurnOutput(
            final_message="Legacy visible copy.",
            confidence=0.9,
            trace_metadata={"legacy_used": True},
        )


@pytest.mark.parametrize(
    ("provider", "expected_failure"),
    [
        (_UnknownActionProvider(), "policy:unknown_action"),
        (_BadFieldProvider(), "policy:field_update_missing_evidence"),
        (_BadLifecycleProvider(), "stage expected"),
        (_LegacyProvider(), "legacy_copy_path_used"),
    ],
)
def test_failure_modes_fail_case(provider, expected_failure):
    async def scenario(session: AsyncSession):
        tenant_id, agent_id = await _seed_tenant(session)
        result = await SimulationLabRunner(
            session,
            provider_name="mock",
            provider=provider,
        ).run_fixture(
            tenant_id=tenant_id,
            agent_id=agent_id,
        )
        await session.commit()
        failures = "\n".join(
            failure for case in result["cases"] for failure in case.failure_reasons
        )
        assert expected_failure in failures

    _run(_with_session(scenario))
