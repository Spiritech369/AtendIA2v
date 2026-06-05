from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.config import Settings, get_settings
from atendia.db.models.tenant import Tenant

RolloutMode = Literal[
    "disabled",
    "shadow",
    "preview",
    "preview_only",
    "manual_send",
    "limited_auto",
    "full",
]

_MODE_ORDER: dict[RolloutMode, int] = {
    "disabled": 0,
    "shadow": 1,
    "preview": 2,
    "preview_only": 2,
    "manual_send": 3,
    "limited_auto": 4,
    "full": 5,
}


class RolloutPolicy(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    tenant_id: UUID
    agent_id: UUID | None = None
    runtime_v2_enabled: bool = False
    shadow_mode_enabled: bool = False
    preview_enabled: bool = False
    send_enabled: bool = False
    actions_enabled: bool = False
    workflow_events_enabled: bool = False
    model_provider_enabled: bool = False
    allowed_agent_ids: list[str] = Field(default_factory=list)
    allowed_channel_ids: list[str] = Field(default_factory=list)
    required_eval_suite_passed: bool = False
    min_eval_score: float | None = Field(default=None, ge=0.0, le=1.0)
    max_actions_per_turn: int | None = Field(default=None, ge=0, le=50)
    rollout_mode: RolloutMode = "disabled"
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("allowed_agent_ids", "allowed_channel_ids", mode="before")
    @classmethod
    def _normalize_string_list(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            return []
        return [str(item) for item in value if item is not None and str(item).strip()]


class RolloutDecision(BaseModel):
    capability: str
    allowed: bool
    reasons: list[str]
    policy: dict[str, Any]
    global_flags: dict[str, Any]


class RolloutPolicyService:
    """Tenant-scoped rollout gate for AgentRuntime v2.

    Global flags remain kill switches. Tenant policy is a second explicit allow
    list so enabling an environment flag cannot silently move tenants into v2.
    """

    def __init__(
        self,
        session: AsyncSession,
        *,
        settings: Settings | None = None,
    ) -> None:
        self._session = session
        self._settings = settings or get_settings()

    async def get_policy(
        self,
        tenant_id: UUID,
        agent_id: UUID | str | None = None,
    ) -> RolloutPolicy:
        config = await self._tenant_config(tenant_id)
        raw = _rollout_config(config)
        merged = _merge_agent_override(raw, agent_id)
        rollout_mode = _rollout_mode(merged.get("rollout_mode"))
        mode_level = _MODE_ORDER[rollout_mode]

        def _bool(name: str, default: bool) -> bool:
            value = merged.get(name)
            return bool(default if value is None else value)

        policy = RolloutPolicy(
            tenant_id=tenant_id,
            agent_id=UUID(str(agent_id)) if agent_id else None,
            runtime_v2_enabled=_bool(
                "runtime_v2_enabled",
                rollout_mode != "disabled",
            ),
            shadow_mode_enabled=_bool("shadow_mode_enabled", mode_level >= 1),
            preview_enabled=_bool("preview_enabled", mode_level >= 2),
            send_enabled=_bool("send_enabled", mode_level >= 3),
            actions_enabled=_bool("actions_enabled", False),
            workflow_events_enabled=_bool("workflow_events_enabled", False),
            model_provider_enabled=_bool("model_provider_enabled", False),
            allowed_agent_ids=list(merged.get("allowed_agent_ids") or []),
            allowed_channel_ids=list(merged.get("allowed_channel_ids") or []),
            required_eval_suite_passed=bool(
                merged.get("required_eval_suite_passed", False)
            ),
            min_eval_score=merged.get("min_eval_score"),
            max_actions_per_turn=merged.get("max_actions_per_turn"),
            rollout_mode=rollout_mode,
            metadata=dict(merged.get("metadata") or {}),
        )
        return policy

    async def can_preview(
        self,
        *,
        tenant_id: UUID,
        agent_id: UUID | str | None = None,
        channel_id: str | None = None,
    ) -> RolloutDecision:
        policy = await self.get_policy(tenant_id, agent_id)
        return self._decision(
            policy,
            "preview",
            global_enabled=self._settings.agent_runtime_v2_enabled,
            tenant_enabled=policy.preview_enabled,
            agent_id=agent_id,
            channel_id=channel_id,
        )

    async def can_shadow(
        self,
        *,
        tenant_id: UUID,
        agent_id: UUID | str | None = None,
        channel_id: str | None = None,
    ) -> RolloutDecision:
        policy = await self.get_policy(tenant_id, agent_id)
        return self._decision(
            policy,
            "shadow",
            global_enabled=self._settings.agent_runtime_v2_enabled,
            tenant_enabled=policy.shadow_mode_enabled,
            agent_id=agent_id,
            channel_id=channel_id,
        )

    async def can_send(
        self,
        *,
        tenant_id: UUID,
        agent_id: UUID | str | None = None,
        channel_id: str | None = None,
    ) -> RolloutDecision:
        policy = await self.get_policy(tenant_id, agent_id)
        decision = self._decision(
            policy,
            "send",
            global_enabled=(
                self._settings.agent_runtime_v2_enabled
                and self._settings.agent_runtime_v2_send_enabled
            ),
            tenant_enabled=policy.send_enabled,
            agent_id=agent_id,
            channel_id=channel_id,
            require_eval=False,
        )
        if policy.required_eval_suite_passed:
            from atendia.eval_lab.readiness import ReadinessService

            readiness = await ReadinessService(self._session).explain_readiness(
                tenant_id=tenant_id,
                agent_id=policy.agent_id,
                min_score=policy.min_eval_score,
            )
            if not readiness.ready:
                decision.allowed = False
                decision.reasons.extend(readiness.reasons)
            else:
                decision.reasons.extend(readiness.reasons)
            decision.policy["readiness"] = readiness.model_dump()
        return decision

    async def can_execute_actions(
        self,
        *,
        tenant_id: UUID,
        agent_id: UUID | str | None = None,
        channel_id: str | None = None,
    ) -> RolloutDecision:
        policy = await self.get_policy(tenant_id, agent_id)
        return self._decision(
            policy,
            "actions",
            global_enabled=(
                self._settings.agent_runtime_v2_enabled
                and self._settings.agent_runtime_v2_actions_enabled
            ),
            tenant_enabled=policy.actions_enabled,
            agent_id=agent_id,
            channel_id=channel_id,
        )

    async def can_emit_workflow_events(
        self,
        *,
        tenant_id: UUID,
        agent_id: UUID | str | None = None,
        channel_id: str | None = None,
    ) -> RolloutDecision:
        policy = await self.get_policy(tenant_id, agent_id)
        return self._decision(
            policy,
            "workflow_events",
            global_enabled=(
                self._settings.agent_runtime_v2_enabled
                and self._settings.agent_runtime_v2_workflow_events_enabled
            ),
            tenant_enabled=policy.workflow_events_enabled,
            agent_id=agent_id,
            channel_id=channel_id,
        )

    async def can_use_model_provider(
        self,
        *,
        tenant_id: UUID,
        agent_id: UUID | str | None = None,
        channel_id: str | None = None,
    ) -> RolloutDecision:
        policy = await self.get_policy(tenant_id, agent_id)
        return self._decision(
            policy,
            "model_provider",
            global_enabled=(
                self._settings.agent_runtime_v2_enabled
                and self._settings.agent_runtime_v2_model_provider != "disabled"
            ),
            tenant_enabled=policy.model_provider_enabled,
            agent_id=agent_id,
            channel_id=channel_id,
        )

    def require_eval_gate(self, policy: RolloutPolicy) -> RolloutDecision:
        return self._eval_gate_decision(policy)

    def explain_decision(self, decision: RolloutDecision) -> dict[str, Any]:
        return decision.model_dump(mode="json")

    async def _tenant_config(self, tenant_id: UUID) -> dict[str, Any]:
        config = (
            await self._session.execute(
                select(Tenant.config).where(Tenant.id == tenant_id)
            )
        ).scalar_one_or_none()
        return dict(config or {})

    def _decision(
        self,
        policy: RolloutPolicy,
        capability: str,
        *,
        global_enabled: bool,
        tenant_enabled: bool,
        agent_id: UUID | str | None = None,
        channel_id: str | None = None,
        require_eval: bool = False,
    ) -> RolloutDecision:
        reasons: list[str] = []
        blocked = False
        if not global_enabled:
            reasons.append(f"global flag blocks {capability}")
            blocked = True
        if not policy.runtime_v2_enabled:
            reasons.append("tenant runtime_v2_enabled is false")
            blocked = True
        if not tenant_enabled:
            reasons.append(f"tenant {capability} is false")
            blocked = True
        if not _agent_allowed(policy, agent_id):
            reasons.append("agent_id is not allowed by tenant rollout policy")
            blocked = True
        if not _channel_allowed(policy, channel_id):
            reasons.append("channel_id is not allowed by tenant rollout policy")
            blocked = True
        if require_eval:
            eval_decision = self._eval_gate_decision(policy)
            if not eval_decision.allowed:
                reasons.extend(eval_decision.reasons)
                blocked = True
        if not blocked:
            reasons.append(f"{capability} allowed by tenant rollout policy")
        return RolloutDecision(
            capability=capability,
            allowed=not blocked,
            reasons=reasons,
            policy=policy.model_dump(mode="json"),
            global_flags=self._global_flags(),
        )

    def _eval_gate_decision(self, policy: RolloutPolicy) -> RolloutDecision:
        reasons: list[str] = []
        if policy.required_eval_suite_passed:
            if not bool(policy.metadata.get("eval_suite_passed")):
                reasons.append("required eval suite has not passed")
            score = _float_or_none(policy.metadata.get("eval_score"))
            if policy.min_eval_score is not None:
                if score is None:
                    reasons.append("eval score is missing or invalid")
                elif score < policy.min_eval_score:
                    reasons.append(
                        f"eval score is below required minimum {policy.min_eval_score}"
                    )
        if not reasons:
            reasons.append("eval gate passed")
        return RolloutDecision(
            capability="eval_gate",
            allowed=not any(reason != "eval gate passed" for reason in reasons),
            reasons=reasons,
            policy=policy.model_dump(mode="json"),
            global_flags=self._global_flags(),
        )

    def _global_flags(self) -> dict[str, Any]:
        return {
            "agent_runtime_v2_enabled": self._settings.agent_runtime_v2_enabled,
            "agent_runtime_v2_send_enabled": self._settings.agent_runtime_v2_send_enabled,
            "agent_runtime_v2_actions_enabled": self._settings.agent_runtime_v2_actions_enabled,
            "agent_runtime_v2_workflow_events_enabled": (
                self._settings.agent_runtime_v2_workflow_events_enabled
            ),
            "agent_runtime_v2_model_provider": (
                self._settings.agent_runtime_v2_model_provider
            ),
        }


def _rollout_config(config: Mapping[str, Any]) -> dict[str, Any]:
    raw = config.get("agent_runtime_v2") or config.get("agent_runtime_v2_rollout") or {}
    return dict(raw) if isinstance(raw, Mapping) else {}


def _merge_agent_override(
    raw: Mapping[str, Any],
    agent_id: UUID | str | None,
) -> dict[str, Any]:
    merged = dict(raw)
    if not agent_id:
        return merged
    overrides = raw.get("agent_overrides") or raw.get("agents") or {}
    if not isinstance(overrides, Mapping):
        return merged
    agent_override = overrides.get(str(agent_id))
    if not isinstance(agent_override, Mapping):
        return merged
    metadata = {
        **dict(merged.get("metadata") or {}),
        **dict(agent_override.get("metadata") or {}),
    }
    merged.update(dict(agent_override))
    merged["metadata"] = metadata
    return merged


def _rollout_mode(value: Any) -> RolloutMode:
    if value in _MODE_ORDER:
        return value
    return "disabled"


def _agent_allowed(policy: RolloutPolicy, agent_id: UUID | str | None) -> bool:
    if not policy.allowed_agent_ids:
        return True
    return agent_id is not None and str(agent_id) in policy.allowed_agent_ids


def _channel_allowed(policy: RolloutPolicy, channel_id: str | None) -> bool:
    if not policy.allowed_channel_ids:
        return True
    return channel_id is not None and str(channel_id) in policy.allowed_channel_ids


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
