from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from atendia.api._auth_helpers import AuthUser
from atendia.api._deps import current_tenant_id, require_tenant_admin
from atendia.blueprints import BlueprintService
from atendia.blueprints.schemas import BlueprintDefinition
from atendia.blueprints.service import BlueprintNotFoundError, BlueprintValidationError
from atendia.db.models.customer_fields import CustomerFieldDefinition
from atendia.db.models.onboarding import OnboardingState
from atendia.db.models.tenant_config import TenantPipeline
from atendia.db.session import get_db_session

router = APIRouter()


class BlueprintListItem(BaseModel):
    id: str
    name: str
    description: str
    industries: list[str]
    knowledge_categories: list[str]
    workflow_template_count: int
    eval_scenario_count: int


class BlueprintPreviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    blueprint: dict[str, Any]
    fields_to_create: list[dict[str, Any]]
    existing_fields: list[dict[str, Any]]
    lifecycle_stages_to_create: list[dict[str, Any]]
    existing_lifecycle_stages: list[dict[str, Any]]
    agent_template: dict[str, Any]
    enabled_actions: list[str]
    knowledge_categories: list[str]
    workflow_draft_templates: list[dict[str, Any]]
    eval_scenarios: list[dict[str, Any]]
    risks: list[dict[str, Any]] = Field(default_factory=list)


@router.get("", response_model=list[BlueprintListItem])
async def list_blueprints(
    user: AuthUser = Depends(require_tenant_admin),
) -> list[BlueprintListItem]:
    del user
    service = BlueprintService()
    return [
        BlueprintListItem(
            id=blueprint.id,
            name=blueprint.name,
            description=blueprint.description,
            industries=list(blueprint.industries),
            knowledge_categories=list(blueprint.knowledge_categories),
            workflow_template_count=len(blueprint.workflow_templates),
            eval_scenario_count=len(blueprint.eval_scenarios),
        )
        for blueprint in service.list_blueprints()
    ]


@router.get("/{blueprint_id}", response_model=BlueprintPreviewResponse)
async def get_blueprint(
    blueprint_id: str,
    user: AuthUser = Depends(require_tenant_admin),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> BlueprintPreviewResponse:
    del user
    return await _preview_response(session, tenant_id=tenant_id, blueprint_id=blueprint_id)


@router.post("/{blueprint_id}/preview-install", response_model=BlueprintPreviewResponse)
async def preview_install_blueprint(
    blueprint_id: str,
    user: AuthUser = Depends(require_tenant_admin),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> BlueprintPreviewResponse:
    del user
    return await _preview_response(session, tenant_id=tenant_id, blueprint_id=blueprint_id)


@router.post("/{blueprint_id}/install")
async def install_blueprint(
    blueprint_id: str,
    user: AuthUser = Depends(require_tenant_admin),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    service = BlueprintService()
    try:
        result = await service.install_blueprint(
            session,
            tenant_id=tenant_id,
            blueprint_id=blueprint_id,
            actor_user_id=user.user_id,
        )
    except BlueprintNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "blueprint not found") from exc
    except BlueprintValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    blueprint = service.get_blueprint(blueprint_id)
    state = await _get_or_create_onboarding_state(session, tenant_id)
    state.selected_blueprint_id = blueprint_id
    state.agent_configured = state.agent_configured or bool(result.agent_id)
    state.contact_fields_ready = state.contact_fields_ready or bool(
        result.created_field_keys or result.skipped_field_keys
    )
    state.lifecycle_ready = state.lifecycle_ready or bool(
        result.created_lifecycle_stage_ids or result.skipped_lifecycle_stage_ids
    )
    if state.current_step == "select_blueprint":
        state.current_step = "connect_channel"
    checklist = dict(state.checklist or {})
    checklist["blueprint_selected"] = True
    checklist["expected_knowledge_categories"] = list(blueprint.knowledge_categories)
    checklist["blueprint_install_result"] = result.model_dump(mode="json")
    state.checklist = checklist
    flag_modified(state, "checklist")
    await session.commit()
    return result.model_dump(mode="json")


@router.post("/{blueprint_id}/create-knowledge-templates")
async def create_knowledge_templates(
    blueprint_id: str,
    user: AuthUser = Depends(require_tenant_admin),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    service = BlueprintService()
    try:
        result = await service.create_draft_knowledge_templates_for_blueprint(
            session,
            tenant_id=tenant_id,
            blueprint_id=blueprint_id,
            actor_user_id=user.user_id,
        )
    except BlueprintNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "blueprint not found") from exc
    except BlueprintValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    await session.commit()
    return result


@router.post("/{blueprint_id}/create-workflow-drafts")
async def create_workflow_drafts(
    blueprint_id: str,
    user: AuthUser = Depends(require_tenant_admin),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    service = BlueprintService()
    try:
        result = await service.create_workflow_drafts_for_blueprint(
            session,
            tenant_id=tenant_id,
            blueprint_id=blueprint_id,
            actor_user_id=user.user_id,
        )
    except BlueprintNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "blueprint not found") from exc
    except BlueprintValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    await session.commit()
    return result


async def _preview_response(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    blueprint_id: str,
) -> BlueprintPreviewResponse:
    service = BlueprintService()
    try:
        blueprint = service.get_blueprint(blueprint_id)
        service.validate_blueprint(blueprint)
    except BlueprintNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "blueprint not found") from exc
    except BlueprintValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    existing_fields = {
        row.key: row
        for row in (
            (
                await session.execute(
                    select(CustomerFieldDefinition).where(
                        CustomerFieldDefinition.tenant_id == tenant_id
                    )
                )
            )
            .scalars()
            .all()
        )
    }
    stage_rows = await _active_lifecycle_stages(session, tenant_id)
    existing_stage_ids = {
        str(stage.get("id")) for stage in stage_rows if isinstance(stage, dict) and stage.get("id")
    }
    fields_to_create = [
        _field_payload(field)
        for field in blueprint.contact_fields
        if field.key not in existing_fields
    ]
    existing_field_payloads = [
        {
            "key": field.key,
            "label": field.label,
            "field_type": field.field_type,
            "source": "tenant",
        }
        for field in existing_fields.values()
        if field.key in {item.key for item in blueprint.contact_fields}
    ]
    stages_to_create = [
        stage.model_dump(mode="json")
        for stage in blueprint.lifecycle_stages
        if stage.id not in existing_stage_ids
    ]
    blueprint_stage_ids = {item.id for item in blueprint.lifecycle_stages}
    existing_stages = [
        stage for stage in stage_rows if str(stage.get("id")) in blueprint_stage_ids
    ]
    return BlueprintPreviewResponse(
        blueprint=_blueprint_summary(blueprint),
        fields_to_create=fields_to_create,
        existing_fields=existing_field_payloads,
        lifecycle_stages_to_create=stages_to_create,
        existing_lifecycle_stages=existing_stages,
        agent_template=blueprint.agent_template.model_dump(mode="json"),
        enabled_actions=list(blueprint.enabled_actions),
        knowledge_categories=list(blueprint.knowledge_categories),
        workflow_draft_templates=[
            template.model_dump(mode="json") for template in blueprint.workflow_templates
        ],
        eval_scenarios=[scenario.model_dump(mode="json") for scenario in blueprint.eval_scenarios],
        risks=_preview_risks(blueprint),
    )


async def _active_lifecycle_stages(session: AsyncSession, tenant_id: UUID) -> list[dict[str, Any]]:
    pipeline = (
        await session.execute(
            select(TenantPipeline)
            .where(TenantPipeline.tenant_id == tenant_id, TenantPipeline.active.is_(True))
            .order_by(TenantPipeline.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if pipeline is None:
        return []
    return [
        stage
        for stage in (pipeline.definition or {}).get("stages", [])
        if isinstance(stage, dict)
    ]


async def _get_or_create_onboarding_state(
    session: AsyncSession,
    tenant_id: UUID,
) -> OnboardingState:
    state = (
        await session.execute(
            select(OnboardingState).where(OnboardingState.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()
    if state is not None:
        return state
    state = OnboardingState(tenant_id=tenant_id)
    session.add(state)
    await session.flush()
    return state


def _blueprint_summary(blueprint: BlueprintDefinition) -> dict[str, Any]:
    return {
        "id": blueprint.id,
        "name": blueprint.name,
        "description": blueprint.description,
        "industries": list(blueprint.industries),
    }


def _field_payload(field: Any) -> dict[str, Any]:
    return {
        "key": field.key,
        "label": field.label,
        "field_type": field.field_type,
        "ordering": field.ordering,
        "write_policy": field.write_policy,
        "confidence_threshold": field.confidence_threshold,
    }


def _preview_risks(blueprint: BlueprintDefinition) -> list[dict[str, Any]]:
    risks: list[dict[str, Any]] = []
    if blueprint.knowledge_categories:
        risks.append(
            {
                "code": "knowledge_required",
                "severity": "medium",
                "message": (
                    "Knowledge categories are expected but draft templates are empty "
                    "until content is uploaded and activated."
                ),
            }
        )
    if blueprint.workflow_templates:
        risks.append(
            {
                "code": "workflow_drafts_inactive",
                "severity": "low",
                "message": (
                    "Workflow templates are created as inactive drafts and require "
                    "manual review before publishing."
                ),
            }
        )
    if blueprint.enabled_actions:
        risks.append(
            {
                "code": "actions_require_approval",
                "severity": "low",
                "message": (
                    "Actions are enabled in agent configuration only; no external "
                    "action is executed by blueprint install."
                ),
            }
        )
    return risks
