from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from atendia.blueprints import BlueprintService
from atendia.config import get_settings
from atendia.contact_memory.policy import policy_config_dict
from atendia.db.models.agent import Agent
from atendia.db.models.customer_fields import CustomerFieldDefinition
from atendia.db.models.event import EventRow
from atendia.db.models.knowledge_os import KnowledgeSource
from atendia.db.models.tenant_config import TenantPipeline


async def _seed_tenant() -> str:
    engine = create_async_engine(get_settings().database_url)
    try:
        async with engine.begin() as conn:
            tenant_id = (
                await conn.execute(
                    text("INSERT INTO tenants (name) VALUES (:n) RETURNING id"),
                    {"n": f"blueprint_v1_{uuid4().hex[:8]}"},
                )
            ).scalar_one()
            return str(tenant_id)
    finally:
        await engine.dispose()


async def _delete_tenant(tenant_id: str) -> None:
    engine = create_async_engine(get_settings().database_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tenant_id})
    finally:
        await engine.dispose()


@pytest.fixture
def tenant_id() -> str:
    created = asyncio.run(_seed_tenant())
    yield created
    asyncio.run(_delete_tenant(created))


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine(get_settings().database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        yield db
        await db.rollback()
    await engine.dispose()


def test_list_and_preview_blueprints_exposes_expected_ids():
    service = BlueprintService()
    ids = {item.id for item in service.list_blueprints()}

    assert ids == {"automotive_real_estate", "dental_clinic", "beauty_barber_spa"}
    preview = service.preview_blueprint("dental_clinic")
    assert "patient_need" in preview.field_keys
    assert "appointment_requested" in preview.lifecycle_stage_ids
    assert preview.eval_scenario_ids


def test_blueprint_definitions_validate_schema_and_registered_actions():
    service = BlueprintService()

    for blueprint in service.list_blueprints():
        service.validate_blueprint(blueprint)
        assert blueprint.contact_fields
        assert blueprint.lifecycle_stages
        assert blueprint.agent_template.instructions


async def test_install_blueprint_in_empty_tenant(session, tenant_id):
    service = BlueprintService()

    result = await service.install_blueprint(
        session,
        tenant_id=UUID(tenant_id),
        blueprint_id="beauty_barber_spa",
    )
    await session.commit()

    assert result.agent_created is True
    assert "requested_service" in result.created_field_keys
    assert "appointment_requested" in result.created_lifecycle_stage_ids
    assert result.eval_scenario_ids

    fields = (
        await session.execute(
            select(CustomerFieldDefinition).where(
                CustomerFieldDefinition.tenant_id == UUID(tenant_id)
            )
        )
    ).scalars().all()
    assert {field.key for field in fields} >= {"requested_service", "preferred_time"}
    requested_service = next(field for field in fields if field.key == "requested_service")
    assert policy_config_dict(requested_service)["evidence_required"] is True

    pipeline = (
        await session.execute(
            select(TenantPipeline).where(TenantPipeline.tenant_id == UUID(tenant_id))
        )
    ).scalar_one()
    stage_ids = [stage["id"] for stage in pipeline.definition["stages"]]
    assert "appointment_requested" in stage_ids
    assert pipeline.definition["metadata"]["blueprints_v1"]["installed"] == [
        "beauty_barber_spa"
    ]

    agent = (
        await session.execute(select(Agent).where(Agent.tenant_id == UUID(tenant_id)))
    ).scalar_one()
    assert agent.system_prompt
    assert agent.ops_config["agent_studio_v2"]["metadata"]["blueprint_id"] == (
        "beauty_barber_spa"
    )
    assert agent.auto_actions["enabled_action_ids"] == [
        "update_contact_field",
        "move_lifecycle",
        "assign_conversation",
        "add_tag",
    ]

    audit_count = (
        await session.execute(
            select(func.count(EventRow.id)).where(
                EventRow.tenant_id == UUID(tenant_id),
                EventRow.type == "admin.blueprint.installed",
            )
        )
    ).scalar_one()
    assert audit_count == 1


async def test_install_blueprint_is_idempotent_for_fields_stages_and_agent(session, tenant_id):
    service = BlueprintService()

    first = await service.install_blueprint(
        session,
        tenant_id=UUID(tenant_id),
        blueprint_id="automotive_real_estate",
    )
    second = await service.install_blueprint(
        session,
        tenant_id=UUID(tenant_id),
        blueprint_id="automotive_real_estate",
    )
    await session.commit()

    assert first.agent_created is True
    assert second.already_installed is True
    assert second.created_field_keys == []
    assert second.created_lifecycle_stage_ids == []

    field_count = (
        await session.execute(
            select(func.count(CustomerFieldDefinition.id)).where(
                CustomerFieldDefinition.tenant_id == UUID(tenant_id),
                CustomerFieldDefinition.key == "interest_item",
            )
        )
    ).scalar_one()
    agent_count = (
        await session.execute(
            select(func.count(Agent.id)).where(Agent.tenant_id == UUID(tenant_id))
        )
    ).scalar_one()
    assert field_count == 1
    assert agent_count == 1


async def test_create_draft_knowledge_templates_for_blueprint_is_idempotent(session, tenant_id):
    service = BlueprintService()

    first = await service.create_draft_knowledge_templates_for_blueprint(
        session,
        tenant_id=UUID(tenant_id),
        blueprint_id="automotive_real_estate",
    )
    second = await service.create_draft_knowledge_templates_for_blueprint(
        session,
        tenant_id=UUID(tenant_id),
        blueprint_id="automotive_real_estate",
    )
    await session.commit()

    assert first["created_categories"] == [
        "catalog",
        "pricing",
        "services",
        "appointment_rules",
        "document_rules",
        "policy",
    ]
    assert second["already_created"] is True
    rows = (
        await session.execute(
            select(KnowledgeSource).where(KnowledgeSource.tenant_id == UUID(tenant_id))
        )
    ).scalars().all()
    assert len(rows) == len(first["created_categories"])
    assert {row.status for row in rows} == {"draft"}
    assert all((row.metadata_json or {}).get("template_empty") is True for row in rows)


async def test_blueprint_installation_is_tenant_isolated(session):
    tenant_a = await _seed_tenant()
    tenant_b = await _seed_tenant()
    try:
        service = BlueprintService()
        await service.install_blueprint(
            session,
            tenant_id=UUID(tenant_a),
            blueprint_id="dental_clinic",
        )
        await session.commit()

        count_a = (
            await session.execute(
                select(func.count(CustomerFieldDefinition.id)).where(
                    CustomerFieldDefinition.tenant_id == UUID(tenant_a)
                )
            )
        ).scalar_one()
        count_b = (
            await session.execute(
                select(func.count(CustomerFieldDefinition.id)).where(
                    CustomerFieldDefinition.tenant_id == UUID(tenant_b)
                )
            )
        ).scalar_one()
        assert count_a > 0
        assert count_b == 0
    finally:
        await _delete_tenant(tenant_a)
        await _delete_tenant(tenant_b)


def test_vertical_terms_stay_out_of_agent_runtime_code():
    runtime_dir = Path(__file__).resolve().parents[2] / "atendia" / "agent_runtime"
    runtime_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in runtime_dir.glob("*.py")
        if path.name != "__pycache__"
    ).casefold()

    assert "dental_clinic" not in runtime_text
    assert "beauty_barber_spa" not in runtime_text
    assert "automotive_real_estate" not in runtime_text
