from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from atendia.api._auth_helpers import AuthUser
from atendia.api._deps import current_tenant_id, require_tenant_admin
from atendia.blueprints import BlueprintService
from atendia.blueprints.service import BlueprintNotFoundError, BlueprintValidationError
from atendia.db.models.agent import Agent
from atendia.db.models.customer_fields import CustomerFieldDefinition
from atendia.db.models.knowledge_document import KnowledgeDocument
from atendia.db.models.knowledge_os import KnowledgeSource
from atendia.db.models.onboarding import OnboardingState
from atendia.db.models.tenant_baileys_config import TenantBaileysConfig
from atendia.db.models.tenant_config import TenantCatalogItem, TenantFAQ, TenantPipeline
from atendia.db.session import get_db_session
from atendia.eval_lab.readiness import ReadinessService, readiness_result_payload

router = APIRouter()

KNOWN_STEP_FIELDS: frozenset[str] = frozenset(
    {
        "channel_connected",
        "knowledge_uploaded",
        "agent_configured",
        "contact_fields_ready",
        "lifecycle_ready",
        "test_passed",
        "published",
    }
)


class OnboardingStateResponse(BaseModel):
    tenant_id: UUID
    selected_blueprint_id: str | None
    channel_connected: bool
    knowledge_uploaded: bool
    agent_configured: bool
    contact_fields_ready: bool
    lifecycle_ready: bool
    test_passed: bool
    published: bool
    current_step: str
    checklist: dict[str, Any]


class SelectBlueprintBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    blueprint_id: str


class SelectBlueprintResponse(BaseModel):
    state: OnboardingStateResponse
    install_result: dict[str, Any]


class MarkStepBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step: str = Field(min_length=2, max_length=80)
    value: bool = True
    current_step: str | None = Field(default=None, max_length=80)
    checklist_updates: dict[str, Any] = Field(default_factory=dict)


class OnboardingCheck(BaseModel):
    code: str
    label: str
    passed: bool
    severity: str = "critical"
    message: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class OnboardingValidationResponse(BaseModel):
    ready: bool
    state: OnboardingStateResponse
    checks: list[OnboardingCheck]
    blocking_codes: list[str]
    readiness: dict[str, Any] | None = None


@router.get("/state", response_model=OnboardingStateResponse)
async def get_onboarding_state(
    user: AuthUser = Depends(require_tenant_admin),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> OnboardingStateResponse:
    del user
    state = await _get_or_create_state(session, tenant_id)
    await session.commit()
    return _state_response(state)


@router.post("/select-blueprint", response_model=SelectBlueprintResponse)
async def select_blueprint(
    body: SelectBlueprintBody,
    user: AuthUser = Depends(require_tenant_admin),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> SelectBlueprintResponse:
    state = await _get_or_create_state(session, tenant_id)
    service = BlueprintService()
    try:
        install_result = await service.install_blueprint(
            session,
            tenant_id=tenant_id,
            blueprint_id=body.blueprint_id,
            actor_user_id=user.user_id,
        )
        template_result = await service.create_draft_knowledge_templates_for_blueprint(
            session,
            tenant_id=tenant_id,
            blueprint_id=body.blueprint_id,
            actor_user_id=user.user_id,
        )
    except BlueprintNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "blueprint not found") from exc
    except BlueprintValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    state.selected_blueprint_id = body.blueprint_id
    state.agent_configured = state.agent_configured or bool(install_result.agent_id)
    state.contact_fields_ready = state.contact_fields_ready or bool(
        install_result.created_field_keys or install_result.skipped_field_keys
    )
    state.lifecycle_ready = state.lifecycle_ready or bool(
        install_result.created_lifecycle_stage_ids or install_result.skipped_lifecycle_stage_ids
    )
    state.current_step = "connect_channel"
    checklist = dict(state.checklist or {})
    checklist["blueprint_selected"] = True
    checklist["expected_knowledge_categories"] = list(
        template_result.get("source_ids", {}).keys()
    )
    checklist["knowledge_templates"] = template_result
    checklist["blueprint_install_result"] = install_result.model_dump(mode="json")
    state.checklist = checklist
    flag_modified(state, "checklist")
    await session.commit()
    await session.refresh(state)
    return SelectBlueprintResponse(
        state=_state_response(state),
        install_result={
            **install_result.model_dump(mode="json"),
            "knowledge_templates": template_result,
        },
    )


@router.post("/mark-step", response_model=OnboardingStateResponse)
async def mark_step(
    body: MarkStepBody,
    user: AuthUser = Depends(require_tenant_admin),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> OnboardingStateResponse:
    del user
    state = await _get_or_create_state(session, tenant_id)
    if body.step in KNOWN_STEP_FIELDS:
        setattr(state, body.step, body.value)
    checklist = dict(state.checklist or {})
    checklist[body.step] = body.value
    checklist.update(body.checklist_updates)
    state.checklist = checklist
    flag_modified(state, "checklist")
    if body.current_step:
        state.current_step = body.current_step
    await session.commit()
    await session.refresh(state)
    return _state_response(state)


@router.post("/validate", response_model=OnboardingValidationResponse)
async def validate_onboarding(
    user: AuthUser = Depends(require_tenant_admin),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> OnboardingValidationResponse:
    del user
    state = await _get_or_create_state(session, tenant_id)
    response = await _validate_state(session, tenant_id, state)
    await session.commit()
    return response


@router.post("/publish-readiness", response_model=OnboardingValidationResponse)
async def publish_readiness(
    user: AuthUser = Depends(require_tenant_admin),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> OnboardingValidationResponse:
    del user
    state = await _get_or_create_state(session, tenant_id)
    response = await _validate_state(session, tenant_id, state)
    await session.commit()
    return response


async def _get_or_create_state(session: AsyncSession, tenant_id: UUID) -> OnboardingState:
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


async def _validate_state(
    session: AsyncSession,
    tenant_id: UUID,
    state: OnboardingState,
) -> OnboardingValidationResponse:
    signals = await _collect_signals(session, tenant_id, state)
    latest_readiness = None
    if signals.active_agent_id is not None:
        latest_readiness = await ReadinessService(session).get_latest_readiness_result(
            tenant_id=tenant_id,
            agent_id=signals.active_agent_id,
        )
    readiness_passed = bool(latest_readiness and latest_readiness.passed)
    checklist = dict(state.checklist or {})
    knowledge_skipped = bool(checklist.get("knowledge_skipped"))
    checks = [
        _check(
            "blueprint_selected",
            "Blueprint selected",
            bool(state.selected_blueprint_id),
            "Select an industry blueprint before publishing.",
        ),
        _check(
            "channel_connected",
            "Channel connected",
            signals.channel_connected,
            "Connect or explicitly verify a WhatsApp/channel before publishing.",
        ),
        _check(
            "active_agent",
            "Agent configured",
            signals.agent_configured,
            "Create and configure at least one agent.",
            {"active_agent_count": signals.active_agent_count},
        ),
        _check(
            "knowledge_ready",
            "Knowledge ready",
            signals.knowledge_uploaded or knowledge_skipped,
            _knowledge_ready_message(signals),
            {
                "active_knowledge_count": signals.active_knowledge_count,
                "knowledge_source_count": signals.knowledge_source_count,
                "draft_template_count": signals.draft_template_count,
                "legacy_knowledge_count": signals.legacy_knowledge_count,
                "knowledge_state": signals.knowledge_state,
                "knowledge_skipped": knowledge_skipped,
                "expected_categories": list(
                    (state.checklist or {}).get("expected_knowledge_categories") or []
                ),
            },
        ),
        _check(
            "lifecycle_ready",
            "Lifecycle ready",
            signals.lifecycle_ready,
            "Configure at least one lifecycle/pipeline stage.",
            {"stage_count": signals.lifecycle_stage_count},
        ),
        _check(
            "contact_fields_ready",
            "Contact fields ready",
            signals.contact_fields_ready,
            "Configure contact fields for operational memory.",
            {"contact_field_count": signals.contact_field_count},
        ),
        _check(
            "test_passed",
            "Test chat passed",
            readiness_passed,
            "Run and pass AgentRuntime v2 readiness before publishing.",
            {
                "readiness": readiness_result_payload(latest_readiness),
                "agent_id": str(signals.active_agent_id) if signals.active_agent_id else None,
            },
        ),
    ]
    blocking_codes = [
        check.code
        for check in checks
        if check.severity == "critical" and not check.passed
    ]
    checks.append(
        _check(
            "no_critical_config_errors",
            "No critical config errors",
            not blocking_codes,
            "Resolve blocking onboarding checks before publishing.",
            {"blocking_codes": blocking_codes},
        )
    )
    ready = not blocking_codes

    state.channel_connected = signals.channel_connected
    state.agent_configured = signals.agent_configured
    state.knowledge_uploaded = signals.knowledge_uploaded
    state.lifecycle_ready = signals.lifecycle_ready
    state.contact_fields_ready = signals.contact_fields_ready
    state.test_passed = readiness_passed
    checklist["last_validation"] = {
        "ready": ready,
        "blocking_codes": blocking_codes,
        "readiness": readiness_result_payload(latest_readiness),
    }
    if readiness_passed:
        checklist["test_passed"] = True
        checklist["readiness"] = readiness_result_payload(latest_readiness)
    state.checklist = checklist
    flag_modified(state, "checklist")
    await session.flush()
    return OnboardingValidationResponse(
        ready=ready,
        state=_state_response(state),
        checks=checks,
        blocking_codes=blocking_codes,
        readiness=readiness_result_payload(latest_readiness),
    )


@dataclass(frozen=True)
class _Signals:
    channel_connected: bool
    agent_configured: bool
    active_agent_count: int
    active_agent_id: UUID | None
    knowledge_uploaded: bool
    active_knowledge_count: int
    knowledge_source_count: int
    draft_template_count: int
    legacy_knowledge_count: int
    knowledge_state: str
    lifecycle_ready: bool
    lifecycle_stage_count: int
    contact_fields_ready: bool
    contact_field_count: int


async def _collect_signals(
    session: AsyncSession,
    tenant_id: UUID,
    state: OnboardingState,
) -> _Signals:
    channel_connected = bool(state.channel_connected) or await _channel_connected(
        session,
        tenant_id,
    )
    active_agent_count = int(
        (
            await session.execute(
                select(func.count(Agent.id)).where(
                    Agent.tenant_id == tenant_id,
                    Agent.status.notin_(["archived", "disabled"]),
                )
            )
        ).scalar_one()
        or 0
    )
    active_agent_id = (
        await session.execute(
            select(Agent.id)
            .where(
                Agent.tenant_id == tenant_id,
                Agent.status.notin_(["archived", "disabled"]),
            )
            .order_by(Agent.created_at.asc())
            .limit(1)
        )
    ).scalar_one_or_none()
    knowledge_counts = await _knowledge_counts(session, tenant_id)
    active_knowledge_count = knowledge_counts["active_total"]
    lifecycle_stage_count = await _lifecycle_stage_count(session, tenant_id)
    contact_field_count = int(
        (
            await session.execute(
                select(func.count(CustomerFieldDefinition.id)).where(
                    CustomerFieldDefinition.tenant_id == tenant_id
                )
            )
        ).scalar_one()
        or 0
    )
    return _Signals(
        channel_connected=channel_connected,
        agent_configured=bool(state.agent_configured) or active_agent_count > 0,
        active_agent_count=active_agent_count,
        active_agent_id=active_agent_id,
        knowledge_uploaded=bool(state.knowledge_uploaded) or active_knowledge_count > 0,
        active_knowledge_count=active_knowledge_count,
        knowledge_source_count=knowledge_counts["source_total"],
        draft_template_count=knowledge_counts["draft_template_total"],
        legacy_knowledge_count=knowledge_counts["legacy_total"],
        knowledge_state=_knowledge_state(knowledge_counts),
        lifecycle_ready=bool(state.lifecycle_ready) or lifecycle_stage_count > 0,
        lifecycle_stage_count=lifecycle_stage_count,
        contact_fields_ready=bool(state.contact_fields_ready) or contact_field_count > 0,
        contact_field_count=contact_field_count,
    )


async def _channel_connected(session: AsyncSession, tenant_id: UUID) -> bool:
    row = (
        await session.execute(
            select(TenantBaileysConfig).where(TenantBaileysConfig.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()
    return bool(row and row.enabled and row.last_status == "connected")


async def _knowledge_counts(session: AsyncSession, tenant_id: UUID) -> dict[str, int]:
    knowledge_os_count = int(
        (
            await session.execute(
                select(func.count(KnowledgeSource.id)).where(
                    KnowledgeSource.tenant_id == tenant_id,
                    KnowledgeSource.status == "active",
                )
            )
        ).scalar_one()
        or 0
    )
    knowledge_source_count = int(
        (
            await session.execute(
                select(func.count(KnowledgeSource.id)).where(
                    KnowledgeSource.tenant_id == tenant_id,
                )
            )
        ).scalar_one()
        or 0
    )
    draft_template_count = int(
        (
            await session.execute(
                select(func.count(KnowledgeSource.id)).where(
                    KnowledgeSource.tenant_id == tenant_id,
                    KnowledgeSource.status == "draft",
                    KnowledgeSource.metadata_json["template_kind"].astext
                    == "blueprint_knowledge",
                )
            )
        ).scalar_one()
        or 0
    )
    legacy_faq_count = int(
        (
            await session.execute(
                select(func.count(TenantFAQ.id)).where(
                    TenantFAQ.tenant_id == tenant_id,
                    TenantFAQ.status == "published",
                )
            )
        ).scalar_one()
        or 0
    )
    legacy_catalog_count = int(
        (
            await session.execute(
                select(func.count(TenantCatalogItem.id)).where(
                    TenantCatalogItem.tenant_id == tenant_id,
                    TenantCatalogItem.active.is_(True),
                    TenantCatalogItem.status == "published",
                )
            )
        ).scalar_one()
        or 0
    )
    legacy_doc_count = int(
        (
            await session.execute(
                select(func.count(KnowledgeDocument.id)).where(
                    KnowledgeDocument.tenant_id == tenant_id,
                    KnowledgeDocument.status.in_(["ready", "active", "published", "embedded"]),
                )
            )
        ).scalar_one()
        or 0
    )
    legacy_total = legacy_faq_count + legacy_catalog_count + legacy_doc_count
    return {
        "active_total": knowledge_os_count + legacy_total,
        "active_native_total": knowledge_os_count,
        "legacy_total": legacy_total,
        "source_total": knowledge_source_count + legacy_total,
        "draft_template_total": draft_template_count,
    }


async def _lifecycle_stage_count(session: AsyncSession, tenant_id: UUID) -> int:
    pipeline = (
        await session.execute(
            select(TenantPipeline.definition)
            .where(TenantPipeline.tenant_id == tenant_id, TenantPipeline.active.is_(True))
            .order_by(TenantPipeline.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if not isinstance(pipeline, dict):
        return 0
    stages = pipeline.get("stages")
    if not isinstance(stages, list):
        return 0
    return len([stage for stage in stages if isinstance(stage, dict) and stage.get("id")])


def _state_response(state: OnboardingState) -> OnboardingStateResponse:
    return OnboardingStateResponse(
        tenant_id=state.tenant_id,
        selected_blueprint_id=state.selected_blueprint_id,
        channel_connected=state.channel_connected,
        knowledge_uploaded=state.knowledge_uploaded,
        agent_configured=state.agent_configured,
        contact_fields_ready=state.contact_fields_ready,
        lifecycle_ready=state.lifecycle_ready,
        test_passed=state.test_passed,
        published=state.published,
        current_step=state.current_step,
        checklist=dict(state.checklist or {}),
    )


def _knowledge_state(counts: dict[str, int]) -> str:
    if counts["active_total"] > 0:
        return "active_source"
    if counts["draft_template_total"] > 0:
        return "draft_template_empty"
    if counts["source_total"] > 0:
        return "no_active_source"
    return "no_source"


def _knowledge_ready_message(signals: _Signals) -> str:
    if signals.knowledge_state == "draft_template_empty":
        return "Blueprint knowledge templates exist, but they are still draft/empty."
    if signals.knowledge_state == "no_active_source":
        return "Knowledge sources exist, but none are active yet."
    return "Upload at least one active knowledge source or mark knowledge_skipped."


def _check(
    code: str,
    label: str,
    passed: bool,
    message: str,
    metadata: dict[str, Any] | None = None,
) -> OnboardingCheck:
    return OnboardingCheck(
        code=code,
        label=label,
        passed=passed,
        message="" if passed else message,
        metadata=metadata or {},
    )
