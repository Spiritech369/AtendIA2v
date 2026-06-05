from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.db.models.tenant_config import TenantPipeline
from atendia.lifecycle.schemas import LifecycleStage


class PipelineLifecycleAdapter:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def load_definition(self, tenant_id: UUID) -> dict[str, Any]:
        definition = (
            await self._session.execute(
                select(TenantPipeline.definition)
                .where(TenantPipeline.tenant_id == tenant_id, TenantPipeline.active.is_(True))
                .order_by(TenantPipeline.version.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        return dict(definition or {})

    async def list_stages(self, tenant_id: UUID) -> list[LifecycleStage]:
        definition = await self.load_definition(tenant_id)
        return self.stages_from_definition(definition)

    def stages_from_definition(self, definition: dict[str, Any]) -> list[LifecycleStage]:
        raw_stages = definition.get("stages")
        if not isinstance(raw_stages, list):
            return []
        stages: list[LifecycleStage] = []
        for index, raw in enumerate(raw_stages):
            if not isinstance(raw, dict) or not raw.get("id"):
                continue
            stage_id = str(raw["id"])
            required_fields = _field_names(raw.get("required_fields"))
            optional_fields = _field_names(raw.get("optional_fields"))
            auto_enter = raw.get("auto_enter_rules")
            transitions = raw.get("transitions")
            allowed_transitions = raw.get("allowed_transitions")
            stages.append(
                LifecycleStage(
                    id=stage_id,
                    key=stage_id,
                    name=str(raw.get("name") or raw.get("label") or stage_id),
                    description=_maybe_str(raw.get("description")),
                    goal=_maybe_str(raw.get("goal")),
                    entry_conditions=_conditions_from_auto_enter(auto_enter),
                    exit_conditions=_transitions_to_conditions(transitions),
                    recommended_fields=[*required_fields, *optional_fields],
                    required_fields=required_fields,
                    recommended_actions=_string_list(raw.get("recommended_actions")),
                    allowed_actions=_string_list(raw.get("actions_allowed")),
                    sla_policy=_sla_policy(raw),
                    automation_policy={
                        "pause_bot_on_enter": bool(raw.get("pause_bot_on_enter")),
                        "handoff_reason": raw.get("handoff_reason"),
                        "allowed_transitions": _string_list(allowed_transitions),
                    },
                    is_lost_stage=bool(raw.get("is_lost_stage") or raw.get("lost")),
                    order=int(raw.get("order") or index),
                    active=raw.get("active") is not False,
                    metadata={
                        key: value
                        for key, value in raw.items()
                        if key
                        not in {
                            "id",
                            "name",
                            "label",
                            "description",
                            "goal",
                            "required_fields",
                            "optional_fields",
                            "actions_allowed",
                            "recommended_actions",
                            "auto_enter_rules",
                            "transitions",
                            "timeout_hours",
                            "timeout_action",
                        }
                    },
                )
            )
        return sorted(stages, key=lambda item: item.order)

    async def get_stage(self, tenant_id: UUID, stage_id: str) -> LifecycleStage | None:
        stages = await self.list_stages(tenant_id)
        return next((stage for stage in stages if stage.id == stage_id), None)

    async def validate_stage_change(
        self,
        *,
        tenant_id: UUID,
        from_stage: str | None,
        to_stage: str,
    ) -> tuple[bool, str, dict[str, Any]]:
        stages = await self.list_stages(tenant_id)
        target = next((stage for stage in stages if stage.id == to_stage), None)
        if target is None or not target.active:
            return False, "unknown lifecycle stage", {"to_stage": to_stage}
        if not from_stage or from_stage == to_stage:
            return True, "stage is valid", {"to_stage": to_stage}
        source = next((stage for stage in stages if stage.id == from_stage), None)
        if source is None:
            return True, "source stage is not in active lifecycle; healing move allowed", {
                "from_stage": from_stage,
                "to_stage": to_stage,
            }
        allowed = source.automation_policy.get("allowed_transitions")
        if isinstance(allowed, list) and allowed and to_stage not in allowed:
            return False, "movement not allowed from source stage", {
                "from_stage": from_stage,
                "to_stage": to_stage,
                "allowed_transitions": allowed,
            }
        return True, "stage change is valid", {"from_stage": from_stage, "to_stage": to_stage}


def _field_names(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    names: list[str] = []
    for item in value:
        if isinstance(item, str):
            names.append(item)
        elif isinstance(item, dict) and item.get("name"):
            names.append(str(item["name"]))
    return list(dict.fromkeys(names))


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return list(dict.fromkeys(str(item) for item in value if str(item).strip()))


def _maybe_str(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _conditions_from_auto_enter(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, dict):
        return []
    conditions = value.get("conditions")
    if not isinstance(conditions, list):
        return []
    return [dict(item) for item in conditions if isinstance(item, dict)]


def _transitions_to_conditions(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _sla_policy(raw: dict[str, Any]) -> dict[str, Any]:
    policy: dict[str, Any] = {}
    if raw.get("timeout_hours") is not None:
        policy["timeout_hours"] = raw.get("timeout_hours")
    if raw.get("timeout_action") is not None:
        policy["timeout_action"] = raw.get("timeout_action")
    return policy
