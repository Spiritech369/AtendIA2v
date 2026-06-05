from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, time
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.db.models.tenant import Tenant
from atendia.db.models.turn_trace import TurnTrace
from atendia.eval_lab.readiness import ReadinessService


class PilotPolicy(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    configured: bool = False
    enabled: bool = False
    tenant_id: UUID
    agent_id: UUID | None = None
    allowed_tenant_ids: list[str] = Field(default_factory=list)
    allowed_agent_ids: list[str] = Field(default_factory=list)
    allowed_channel_ids: list[str] = Field(default_factory=list)
    max_sends_per_day: int = Field(default=1, ge=0)
    require_latest_readiness_passed: bool = True
    min_readiness_score: float | None = Field(default=None, ge=0.0, le=1.0)
    min_shadow_sample_size: int = Field(default=0, ge=0)
    min_shadow_score: float | None = Field(default=None, ge=0.0, le=1.0)
    actions_dry_run_required: bool = True
    workflow_events_dry_run_required: bool = True
    rollback_disabled: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class PilotDecision(BaseModel):
    capability: str = "pilot_send"
    allowed: bool
    reasons: list[str]
    policy: dict[str, Any]
    send_count_today: int = 0
    send_count_after: int = 0
    shadow_sample_size: int = 0
    shadow_average_score: float | None = None

    def trace_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class AgentRuntimeV2PilotPolicyService:
    """Tenant-scoped guard for the limited manual-send v2 pilot."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def can_send(
        self,
        *,
        tenant_id: UUID,
        agent_id: UUID | None,
        channel_id: str | None = None,
    ) -> PilotDecision:
        policy = await self.get_policy(tenant_id=tenant_id, agent_id=agent_id)
        if not policy.configured:
            return PilotDecision(
                allowed=True,
                reasons=["pilot policy not configured; legacy rollout send path applies"],
                policy=policy.model_dump(mode="json"),
            )

        reasons: list[str] = []
        blocked = False
        if not policy.enabled:
            reasons.append("pilot policy is disabled")
            blocked = True
        if policy.rollback_disabled:
            reasons.append("pilot rollback is active")
            blocked = True
        if str(tenant_id) not in set(policy.allowed_tenant_ids):
            reasons.append("tenant_id is not allowlisted for pilot")
            blocked = True
        if agent_id is None or str(agent_id) not in set(policy.allowed_agent_ids):
            reasons.append("agent_id is not allowlisted for pilot")
            blocked = True
        if policy.allowed_channel_ids and channel_id not in set(policy.allowed_channel_ids):
            reasons.append("channel_id is not allowlisted for pilot")
            blocked = True

        send_count = await self._pilot_sends_today(tenant_id=tenant_id, agent_id=agent_id)
        if send_count >= policy.max_sends_per_day:
            reasons.append("pilot max_sends_per_day exceeded")
            blocked = True

        readiness_payload: dict[str, Any] | None = None
        if policy.require_latest_readiness_passed:
            readiness = await ReadinessService(self._session).explain_readiness(
                tenant_id=tenant_id,
                agent_id=agent_id,
                min_score=policy.min_readiness_score,
            )
            readiness_payload = readiness.model_dump()
            if not readiness.ready:
                reasons.extend(readiness.reasons)
                blocked = True
            else:
                reasons.extend(readiness.reasons)

        shadow_stats = await self._shadow_stats(tenant_id=tenant_id, agent_id=agent_id)
        if shadow_stats["sample_size"] < policy.min_shadow_sample_size:
            reasons.append("pilot shadow sample size is below required minimum")
            blocked = True
        shadow_average = shadow_stats["average_score"]
        if (
            policy.min_shadow_score is not None
            and shadow_average is not None
            and shadow_average < policy.min_shadow_score
        ):
            reasons.append("pilot shadow score is below required minimum")
            blocked = True
        if policy.min_shadow_score is not None and shadow_average is None:
            reasons.append("pilot shadow score is missing")
            blocked = True

        if not blocked:
            reasons.append("pilot send allowed")
        policy_payload = policy.model_dump(mode="json")
        if readiness_payload is not None:
            policy_payload["readiness"] = readiness_payload
        return PilotDecision(
            allowed=not blocked,
            reasons=reasons,
            policy=policy_payload,
            send_count_today=send_count,
            send_count_after=send_count + (0 if blocked else 1),
            shadow_sample_size=shadow_stats["sample_size"],
            shadow_average_score=shadow_average,
        )

    async def get_policy(self, *, tenant_id: UUID, agent_id: UUID | None = None) -> PilotPolicy:
        config = await self._tenant_config(tenant_id)
        rollout = _rollout_config(config)
        raw = rollout.get("pilot")
        if not isinstance(raw, Mapping):
            return PilotPolicy(tenant_id=tenant_id, agent_id=agent_id)
        merged = dict(raw)
        overrides = merged.get("agent_overrides") or merged.get("agents") or {}
        if agent_id is not None and isinstance(overrides, Mapping):
            agent_override = overrides.get(str(agent_id))
            if isinstance(agent_override, Mapping):
                metadata = {
                    **dict(merged.get("metadata") or {}),
                    **dict(agent_override.get("metadata") or {}),
                }
                merged.update(dict(agent_override))
                merged["metadata"] = metadata
        return PilotPolicy(
            configured=True,
            tenant_id=tenant_id,
            agent_id=agent_id,
            enabled=bool(merged.get("enabled", False)),
            allowed_tenant_ids=_string_list(merged.get("allowed_tenant_ids")),
            allowed_agent_ids=_string_list(merged.get("allowed_agent_ids")),
            allowed_channel_ids=_string_list(merged.get("allowed_channel_ids")),
            max_sends_per_day=int(merged.get("max_sends_per_day", 1) or 0),
            require_latest_readiness_passed=bool(
                merged.get("require_latest_readiness_passed", True)
            ),
            min_readiness_score=_float_or_none(merged.get("min_readiness_score")),
            min_shadow_sample_size=int(merged.get("min_shadow_sample_size", 0) or 0),
            min_shadow_score=_float_or_none(merged.get("min_shadow_score")),
            actions_dry_run_required=bool(merged.get("actions_dry_run_required", True)),
            workflow_events_dry_run_required=bool(
                merged.get("workflow_events_dry_run_required", True)
            ),
            rollback_disabled=bool(merged.get("rollback_disabled", False)),
            metadata=dict(merged.get("metadata") or {}),
        )

    async def build_report(self, *, tenant_id: UUID) -> dict[str, Any]:
        traces = (
            await self._session.execute(
                select(TurnTrace)
                .where(
                    TurnTrace.tenant_id == tenant_id,
                    TurnTrace.router_trigger.in_(
                        [
                            "agent_runtime_v2_send",
                            "agent_runtime_v2_send_blocked",
                            "agent_runtime_v2_pilot_blocked",
                            "agent_runtime_v2_policy_error",
                        ]
                    ),
                )
                .order_by(TurnTrace.created_at.desc())
            )
        ).scalars().all()
        pilot_traces = [
            trace for trace in traces if _pilot_payload(trace.state_after) is not None
        ]
        send_traces = [
            trace
            for trace in pilot_traces
            if trace.router_trigger == "agent_runtime_v2_send"
        ]
        confidences = [
            confidence
            for confidence in (_confidence(trace.composer_output) for trace in send_traces)
            if confidence is not None
        ]
        actions = sum(len(_list_output(trace.composer_output, "actions")) for trace in send_traces)
        field_suggested = sum(
            len(_list_output(trace.composer_output, "field_updates")) for trace in send_traces
        )
        lifecycle_suggested = sum(
            1 for trace in send_traces if _dict_output(trace.composer_output, "lifecycle_update")
        )
        error_count = sum(1 for trace in pilot_traces if trace.errors)
        return {
            "tenant_id": str(tenant_id),
            "sends": len(send_traces),
            "policy_failures": sum(
                1
                for trace in pilot_traces
                if trace.router_trigger
                in {"agent_runtime_v2_pilot_blocked", "agent_runtime_v2_send_blocked"}
            ),
            "average_confidence": (
                round(sum(confidences) / len(confidences), 4) if confidences else None
            ),
            "needs_human_count": sum(
                1 for trace in send_traces if bool((trace.composer_output or {}).get("needs_human"))
            ),
            "knowledge_gap_count": sum(
                1
                for trace in send_traces
                if "knowledge_gap" in set((trace.composer_output or {}).get("risk_flags") or [])
            ),
            "policy_blocked_count": sum(
                1
                for trace in pilot_traces
                if trace.router_trigger
                in {"agent_runtime_v2_send_blocked", "agent_runtime_v2_policy_error"}
                or bool(trace.errors)
            ),
            "actions_proposed": actions,
            "fields_suggested": field_suggested,
            "fields_applied": _applied_count(send_traces, "update_contact_field"),
            "lifecycle_suggested": lifecycle_suggested,
            "lifecycle_applied": _applied_count(send_traces, "move_lifecycle"),
            "error_rate": round(error_count / len(pilot_traces), 4) if pilot_traces else 0.0,
            "trace_count": len(pilot_traces),
        }

    async def _tenant_config(self, tenant_id: UUID) -> dict[str, Any]:
        config = (
            await self._session.execute(
                select(Tenant.config).where(Tenant.id == tenant_id)
            )
        ).scalar_one_or_none()
        return dict(config or {})

    async def _pilot_sends_today(self, *, tenant_id: UUID, agent_id: UUID | None) -> int:
        start = datetime.combine(datetime.now(UTC).date(), time.min, tzinfo=UTC)
        rows = (
            await self._session.execute(
                select(TurnTrace)
                .where(
                    TurnTrace.tenant_id == tenant_id,
                    TurnTrace.router_trigger == "agent_runtime_v2_send",
                    TurnTrace.created_at >= start,
                )
            )
        ).scalars().all()
        return sum(
            1
            for row in rows
            if _pilot_payload(row.state_after) is not None
            and (agent_id is None or row.agent_id == agent_id)
        )

    async def _shadow_stats(self, *, tenant_id: UUID, agent_id: UUID | None) -> dict[str, Any]:
        rows = (
            await self._session.execute(
                select(TurnTrace).where(
                    TurnTrace.tenant_id == tenant_id,
                    TurnTrace.router_trigger.in_(
                        ["agent_runtime_v2_shadow", "agent_runtime_v2_shadow_auto"]
                    ),
                )
            )
        ).scalars().all()
        filtered = [
            row for row in rows if agent_id is None or row.agent_id == agent_id
        ]
        scores = [
            score
            for score in (_confidence(row.composer_output) for row in filtered)
            if score is not None
        ]
        return {
            "sample_size": len(filtered),
            "average_score": round(sum(scores) / len(scores), 4) if scores else None,
        }


def _rollout_config(config: Mapping[str, Any]) -> dict[str, Any]:
    raw = config.get("agent_runtime_v2") or config.get("agent_runtime_v2_rollout") or {}
    return dict(raw) if isinstance(raw, Mapping) else {}


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item is not None and str(item).strip()]


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _pilot_payload(state_after: dict | None) -> dict[str, Any] | None:
    if not isinstance(state_after, dict):
        return None
    value = state_after.get("pilot")
    return value if isinstance(value, dict) else None


def _confidence(output: dict | None) -> float | None:
    if not isinstance(output, dict):
        return None
    value = output.get("confidence")
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _list_output(output: dict | None, key: str) -> list[Any]:
    if not isinstance(output, dict):
        return []
    value = output.get(key)
    return value if isinstance(value, list) else []


def _dict_output(output: dict | None, key: str) -> dict[str, Any] | None:
    if not isinstance(output, dict):
        return None
    value = output.get(key)
    return value if isinstance(value, dict) else None


def _applied_count(traces: list[TurnTrace], action_name: str) -> int:
    count = 0
    for trace in traces:
        state_after = trace.state_after or {}
        action_results = state_after.get("action_results")
        if not isinstance(action_results, list):
            continue
        count += sum(
            1
            for result in action_results
            if isinstance(result, dict)
            and result.get("action_name") == action_name
            and result.get("status") == "succeeded"
        )
    return count
