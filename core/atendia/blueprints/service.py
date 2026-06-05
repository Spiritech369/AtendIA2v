from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from importlib.resources import files
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.agent_runtime.action_registry import default_action_registry
from atendia.api._audit import emit_admin_event
from atendia.blueprints.schemas import (
    BlueprintDefinition,
    BlueprintInstallResult,
    BlueprintPreview,
)
from atendia.contact_memory.policy import merge_policy_options
from atendia.db.models.agent import Agent
from atendia.db.models.customer_fields import CustomerFieldDefinition
from atendia.db.models.knowledge_os import KnowledgeSource
from atendia.db.models.tenant_config import TenantPipeline
from atendia.db.models.workflow import Workflow
from atendia.workflows.engine import TRIGGERS

BLUEPRINT_METADATA_KEY = "blueprints_v1"
AGENT_STUDIO_V2_KEY = "agent_studio_v2"


class BlueprintNotFoundError(KeyError):
    pass


class BlueprintValidationError(ValueError):
    pass


class BlueprintService:
    def __init__(self, definitions_package: str = "atendia.blueprints.definitions") -> None:
        self._definitions_package = definitions_package

    def list_blueprints(self) -> list[BlueprintDefinition]:
        return sorted(self._load_all(), key=lambda item: item.id)

    def preview_blueprint(self, blueprint_id: str) -> BlueprintPreview:
        blueprint = self.get_blueprint(blueprint_id)
        return BlueprintPreview(
            blueprint=blueprint,
            field_keys=[field.key for field in blueprint.contact_fields],
            lifecycle_stage_ids=[stage.id for stage in blueprint.lifecycle_stages],
            enabled_actions=list(blueprint.enabled_actions),
            knowledge_categories=list(blueprint.knowledge_categories),
            eval_scenario_ids=[scenario.id for scenario in blueprint.eval_scenarios],
        )

    def get_blueprint(self, blueprint_id: str) -> BlueprintDefinition:
        for blueprint in self._load_all():
            if blueprint.id == blueprint_id:
                return blueprint
        raise BlueprintNotFoundError(blueprint_id)

    def validate_blueprint(self, blueprint: BlueprintDefinition) -> None:
        field_keys = [field.key for field in blueprint.contact_fields]
        if len(field_keys) != len(set(field_keys)):
            raise BlueprintValidationError("contact field keys must be unique")
        stage_ids = [stage.id for stage in blueprint.lifecycle_stages]
        if len(stage_ids) != len(set(stage_ids)):
            raise BlueprintValidationError("lifecycle stage ids must be unique")
        scenario_ids = [scenario.id for scenario in blueprint.eval_scenarios]
        if len(scenario_ids) != len(set(scenario_ids)):
            raise BlueprintValidationError("eval scenario ids must be unique")

        available_actions = {
            item.name
            for item in default_action_registry().list_definitions()
            if item.enabled
        }
        action_refs = set(blueprint.enabled_actions)
        for stage in blueprint.lifecycle_stages:
            action_refs.update(stage.recommended_actions)
            action_refs.update(stage.allowed_actions)
        unknown = sorted(action_refs - available_actions)
        if unknown:
            raise BlueprintValidationError(f"unknown action ids: {', '.join(unknown)}")

    async def install_blueprint(
        self,
        session: AsyncSession,
        *,
        tenant_id: UUID,
        blueprint_id: str,
        actor_user_id: UUID | None = None,
    ) -> BlueprintInstallResult:
        blueprint = self.get_blueprint(blueprint_id)
        self.validate_blueprint(blueprint)

        result = BlueprintInstallResult(
            blueprint_id=blueprint.id,
            tenant_id=str(tenant_id),
            workflow_template_ids=[item.id for item in blueprint.workflow_templates],
            eval_scenario_ids=[item.id for item in blueprint.eval_scenarios],
        )
        result.created_field_keys, result.skipped_field_keys = await self._install_fields(
            session,
            tenant_id=tenant_id,
            blueprint=blueprint,
        )
        (
            result.created_lifecycle_stage_ids,
            result.skipped_lifecycle_stage_ids,
        ) = await self._install_lifecycle(
            session,
            tenant_id=tenant_id,
            blueprint=blueprint,
        )
        agent, created = await self._install_agent(
            session,
            tenant_id=tenant_id,
            blueprint=blueprint,
        )
        result.agent_id = str(agent.id)
        result.agent_created = created
        result.already_installed = (
            not result.created_field_keys
            and not result.created_lifecycle_stage_ids
            and not result.agent_created
        )
        await emit_admin_event(
            session,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            action="blueprint.installed",
            payload={
                "blueprint_id": blueprint.id,
                "already_installed": result.already_installed,
                "created_field_keys": result.created_field_keys,
                "created_lifecycle_stage_ids": result.created_lifecycle_stage_ids,
                "agent_id": result.agent_id,
                "agent_created": result.agent_created,
            },
        )
        await session.flush()
        return result

    async def create_draft_knowledge_templates_for_blueprint(
        self,
        session: AsyncSession,
        *,
        tenant_id: UUID,
        blueprint_id: str,
        actor_user_id: UUID | None = None,
    ) -> dict[str, Any]:
        blueprint = self.get_blueprint(blueprint_id)
        self.validate_blueprint(blueprint)
        existing_rows = (
            (
                await session.execute(
                    select(KnowledgeSource).where(KnowledgeSource.tenant_id == tenant_id)
                )
            )
            .scalars()
            .all()
        )
        existing_categories = {
            str((row.metadata_json or {}).get("blueprint_category"))
            for row in existing_rows
            if (row.metadata_json or {}).get("blueprint_id") == blueprint.id
            and (row.metadata_json or {}).get("template_kind") == "blueprint_knowledge"
        }
        created: list[str] = []
        skipped: list[str] = []
        source_ids: dict[str, str] = {}
        for category in blueprint.knowledge_categories:
            if category in existing_categories:
                skipped.append(category)
                row = next(
                    item
                    for item in existing_rows
                    if (item.metadata_json or {}).get("blueprint_id") == blueprint.id
                    and (item.metadata_json or {}).get("template_kind")
                    == "blueprint_knowledge"
                    and (item.metadata_json or {}).get("blueprint_category") == category
                )
                source_ids[category] = str(row.id)
                continue
            row = KnowledgeSource(
                tenant_id=tenant_id,
                name=f"{blueprint.name}: {category.replace('_', ' ').title()}",
                type="manual",
                content_type=_knowledge_content_type(category),
                status="draft",
                priority=0,
                metadata_json={
                    "source_kind": "native",
                    "template_kind": "blueprint_knowledge",
                    "template_empty": True,
                    "blueprint_id": blueprint.id,
                    "blueprint_category": category,
                },
            )
            session.add(row)
            await session.flush()
            created.append(category)
            source_ids[category] = str(row.id)
        if created:
            await emit_admin_event(
                session,
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                action="blueprint.knowledge_templates.created",
                payload={
                    "blueprint_id": blueprint.id,
                    "created_categories": created,
                    "skipped_categories": skipped,
                    "source_ids": source_ids,
                },
            )
        await session.flush()
        return {
            "blueprint_id": blueprint.id,
            "tenant_id": str(tenant_id),
            "created_categories": created,
            "skipped_categories": skipped,
            "source_ids": source_ids,
            "already_created": not created,
        }

    async def create_workflow_drafts_for_blueprint(
        self,
        session: AsyncSession,
        *,
        tenant_id: UUID,
        blueprint_id: str,
        actor_user_id: UUID | None = None,
    ) -> dict[str, Any]:
        blueprint = self.get_blueprint(blueprint_id)
        self.validate_blueprint(blueprint)
        existing_rows = (
            (
                await session.execute(
                    select(Workflow).where(Workflow.tenant_id == tenant_id)
                )
            )
            .scalars()
            .all()
        )
        existing_template_ids = {
            str(((row.definition or {}).get("metadata") or {}).get("blueprint_template_id"))
            for row in existing_rows
            if ((row.definition or {}).get("metadata") or {}).get("blueprint_id")
            == blueprint.id
            and ((row.definition or {}).get("metadata") or {}).get("template_kind")
            == "blueprint_workflow"
        }
        created: list[str] = []
        skipped: list[str] = []
        workflow_ids: dict[str, str] = {}
        for template in blueprint.workflow_templates:
            if template.id in existing_template_ids:
                skipped.append(template.id)
                row = next(
                    item
                    for item in existing_rows
                    if ((item.definition or {}).get("metadata") or {}).get(
                        "blueprint_id"
                    )
                    == blueprint.id
                    and ((item.definition or {}).get("metadata") or {}).get(
                        "template_kind"
                    )
                    == "blueprint_workflow"
                    and ((item.definition or {}).get("metadata") or {}).get(
                        "blueprint_template_id"
                    )
                    == template.id
                )
                workflow_ids[template.id] = str(row.id)
                continue

            definition = deepcopy(template.definition or {"nodes": [], "edges": []})
            definition.setdefault("nodes", [])
            definition.setdefault("edges", [])
            metadata = dict(definition.get("metadata") or {})
            metadata.update(
                {
                    "template_kind": "blueprint_workflow",
                    "template_empty": bool(template.stub),
                    "status": "draft",
                    "blueprint_id": blueprint.id,
                    "blueprint_template_id": template.id,
                    "created_from_blueprint": True,
                }
            )
            definition["metadata"] = metadata
            trigger_type = (
                template.trigger_type
                if template.trigger_type in TRIGGERS and template.trigger_type != "webhook_received"
                else "manual"
            )
            trigger_config = dict(template.trigger_config or {})
            trigger_config.update(
                {
                    "blueprint_id": blueprint.id,
                    "blueprint_template_id": template.id,
                    "safe_draft": True,
                }
            )
            row = Workflow(
                tenant_id=tenant_id,
                name=f"{blueprint.name}: {template.name}",
                description=(
                    "Draft workflow template from blueprint. Review and publish manually."
                ),
                trigger_type=trigger_type,
                trigger_config=trigger_config,
                definition=definition,
                active=False,
            )
            session.add(row)
            await session.flush()
            created.append(template.id)
            workflow_ids[template.id] = str(row.id)

        if created:
            await emit_admin_event(
                session,
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                action="blueprint.workflow_drafts.created",
                payload={
                    "blueprint_id": blueprint.id,
                    "created_template_ids": created,
                    "skipped_template_ids": skipped,
                    "workflow_ids": workflow_ids,
                },
            )
        await session.flush()
        return {
            "blueprint_id": blueprint.id,
            "tenant_id": str(tenant_id),
            "created_template_ids": created,
            "skipped_template_ids": skipped,
            "workflow_ids": workflow_ids,
            "already_created": not created,
        }

    def _load_all(self) -> list[BlueprintDefinition]:
        root = files(self._definitions_package)
        blueprints: list[BlueprintDefinition] = []
        for item in root.iterdir():
            if item.name.endswith(".json"):
                blueprints.append(BlueprintDefinition.model_validate_json(item.read_text()))
        for blueprint in blueprints:
            self.validate_blueprint(blueprint)
        return blueprints

    async def _install_fields(
        self,
        session: AsyncSession,
        *,
        tenant_id: UUID,
        blueprint: BlueprintDefinition,
    ) -> tuple[list[str], list[str]]:
        existing = set(
            (
                await session.execute(
                    select(CustomerFieldDefinition.key).where(
                        CustomerFieldDefinition.tenant_id == tenant_id
                    )
                )
            )
            .scalars()
            .all()
        )
        created: list[str] = []
        skipped: list[str] = []
        for field in blueprint.contact_fields:
            if field.key in existing:
                skipped.append(field.key)
                continue
            options = merge_policy_options(
                field.field_options,
                {
                    "extractable_by_ai": field.extractable_by_ai,
                    "write_policy": field.write_policy,
                    "confidence_threshold": field.confidence_threshold,
                    "evidence_required": field.evidence_required,
                    "prompt_visible": field.prompt_visible,
                    "lifecycle_relevant": field.lifecycle_relevant,
                    "pii": field.pii,
                    "sensitive": field.sensitive,
                },
            )
            options = dict(options or {})
            options[BLUEPRINT_METADATA_KEY] = {
                "blueprint_id": blueprint.id,
                "installed_at": datetime.now(UTC).isoformat(),
            }
            session.add(
                CustomerFieldDefinition(
                    tenant_id=tenant_id,
                    key=field.key,
                    label=field.label,
                    field_type=field.field_type,
                    field_options=options,
                    ordering=field.ordering,
                )
            )
            existing.add(field.key)
            created.append(field.key)
        await session.flush()
        return created, skipped

    async def _install_lifecycle(
        self,
        session: AsyncSession,
        *,
        tenant_id: UUID,
        blueprint: BlueprintDefinition,
    ) -> tuple[list[str], list[str]]:
        pipeline = (
            await session.execute(
                select(TenantPipeline)
                .where(TenantPipeline.tenant_id == tenant_id, TenantPipeline.active.is_(True))
                .order_by(TenantPipeline.version.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if pipeline is None:
            version = (
                await session.execute(
                    select(func.coalesce(func.max(TenantPipeline.version), 0) + 1).where(
                        TenantPipeline.tenant_id == tenant_id
                    )
                )
            ).scalar_one()
            definition: dict[str, Any] = {
                "version": 1,
                "stages": [],
                "metadata": {BLUEPRINT_METADATA_KEY: {"installed": []}},
            }
            pipeline = TenantPipeline(
                tenant_id=tenant_id,
                version=int(version),
                definition=definition,
                active=True,
                history=[],
            )
            session.add(pipeline)
            await session.flush()
        definition = deepcopy(pipeline.definition or {})
        stages = list(definition.get("stages") or [])
        existing_ids = {
            str(stage.get("id"))
            for stage in stages
            if isinstance(stage, dict) and stage.get("id")
        }
        created: list[str] = []
        skipped: list[str] = []
        for stage in sorted(blueprint.lifecycle_stages, key=lambda item: item.order):
            if stage.id in existing_ids:
                skipped.append(stage.id)
                continue
            stages.append(_stage_to_pipeline(stage.model_dump(), blueprint_id=blueprint.id))
            existing_ids.add(stage.id)
            created.append(stage.id)
        metadata = dict(definition.get("metadata") or {})
        bp_meta = dict(metadata.get(BLUEPRINT_METADATA_KEY) or {})
        installed = list(bp_meta.get("installed") or [])
        if blueprint.id not in installed:
            installed.append(blueprint.id)
        bp_meta["installed"] = installed
        bp_meta["updated_at"] = datetime.now(UTC).isoformat()
        metadata[BLUEPRINT_METADATA_KEY] = bp_meta
        definition["metadata"] = metadata
        definition["stages"] = stages
        pipeline.definition = definition
        pipeline.active = True
        await session.flush()
        return created, skipped

    async def _install_agent(
        self,
        session: AsyncSession,
        *,
        tenant_id: UUID,
        blueprint: BlueprintDefinition,
    ) -> tuple[Agent, bool]:
        existing_agents = (
            await session.execute(select(Agent).where(Agent.tenant_id == tenant_id))
        ).scalars().all()
        for agent in existing_agents:
            studio = ((agent.ops_config or {}).get(AGENT_STUDIO_V2_KEY) or {})
            metadata = studio.get("metadata") or {}
            if metadata.get("blueprint_id") == blueprint.id:
                return agent, False

        template = blueprint.agent_template
        studio_config = {
            "template": template.role,
            "instructions": template.instructions,
            "language_policy": template.language_policy,
            "enabled_knowledge_source_ids": [],
            "enabled_action_ids": list(blueprint.enabled_actions),
            "visible_contact_field_keys": [field.key for field in blueprint.contact_fields],
            "allowed_lifecycle_stage_ids": [stage.id for stage in blueprint.lifecycle_stages],
            "escalation_policy": template.escalation_policy,
            "metadata": {
                "blueprint_id": blueprint.id,
                "industries": list(blueprint.industries),
                "knowledge_categories": list(blueprint.knowledge_categories),
            },
        }
        agent = Agent(
            tenant_id=tenant_id,
            name=template.name,
            role=template.role,
            status="draft",
            tone=template.tone,
            language=str(template.language_policy.get("primary") or "es-MX"),
            system_prompt=template.instructions,
            is_default=not bool(existing_agents),
            auto_actions={"enabled_action_ids": list(blueprint.enabled_actions)},
            knowledge_config={
                "enabled_source_ids": [],
                "expected_categories": list(blueprint.knowledge_categories),
                "blueprint_id": blueprint.id,
            },
            extraction_config={
                "visible_contact_field_keys": [field.key for field in blueprint.contact_fields]
            },
            flow_mode_rules={
                "allowed_stage_ids": [stage.id for stage in blueprint.lifecycle_stages]
            },
            ops_config={
                AGENT_STUDIO_V2_KEY: studio_config,
                BLUEPRINT_METADATA_KEY: {
                    "blueprint_id": blueprint.id,
                    "installed_at": datetime.now(UTC).isoformat(),
                },
            },
        )
        session.add(agent)
        await session.flush()
        return agent, True


def _stage_to_pipeline(stage: dict[str, Any], *, blueprint_id: str) -> dict[str, Any]:
    return {
        "id": stage["id"],
        "label": stage["name"],
        "description": stage.get("description") or "",
        "goal": stage.get("goal") or "",
        "entry_conditions": stage.get("entry_conditions") or [],
        "exit_conditions": stage.get("exit_conditions") or [],
        "recommended_fields": stage.get("recommended_fields") or [],
        "required_fields": stage.get("required_fields") or [],
        "recommended_actions": stage.get("recommended_actions") or [],
        "allowed_actions": stage.get("allowed_actions") or [],
        "automation_policy": stage.get("automation_policy") or {},
        "is_lost_stage": bool(stage.get("is_lost_stage")),
        "order": int(stage.get("order") or 0),
        "active": bool(stage.get("active", True)),
        "blueprint_id": blueprint_id,
    }


def _knowledge_content_type(category: str) -> str:
    allowed = {
        "faq",
        "policy",
        "pricing",
        "catalog",
        "services",
        "appointment_rules",
        "document_rules",
        "general",
    }
    normalized = category.strip().lower()
    return normalized if normalized in allowed else "general"
