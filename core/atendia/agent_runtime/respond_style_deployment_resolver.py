from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

JsonDict = dict[str, Any]

RoutePreview = Literal["product_agent_direct", "legacy_runner"]


class DeploymentView(BaseModel):
    """Read-only view of an agent deployment (mapped from the deployment
    record by the caller; this module never touches the DB)."""

    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    deployment_id: str
    agent_id: str
    active_version_id: str | None = None
    channel: str = "test_lab"
    environment: str = "no_send"
    publish_state: str = "draft"
    runtime_mode: str = "test_lab_no_send"
    respond_style_enabled: bool = False
    send_enabled: bool = False
    outbox_enabled: bool = False
    live_send_enabled: bool = False
    metadata: JsonDict = Field(default_factory=dict)


class DeploymentResolution(BaseModel):
    """Preview-only routing decision. This object never executes anything:
    it states which route a published Product Agent WOULD take and which
    live gates remain closed. send stays no_send by construction."""

    model_config = ConfigDict(extra="forbid")

    route_preview: RoutePreview
    reason: str
    no_send_only: Literal[True] = True
    send_decision: Literal["no_send"] = "no_send"
    live_routing_active: Literal[False] = False
    live_blocked_reasons: list[str] = Field(default_factory=list)
    deployment_id: str
    agent_id: str
    active_version_id: str | None = None


class RespondStyleDeploymentResolver:
    """Decides (preview, no-send) whether a deployment belongs on the
    Product-First direct route or stays on the frozen legacy runner.

    This is the future legacy-runner-bypass switch. In this phase it
    only previews: it does not route live traffic, does not import or call
    any runner, and every resolution is no_send.
    """

    def resolve(self, deployment: DeploymentView) -> DeploymentResolution:
        blockers = _direct_route_blockers(deployment)
        if blockers:
            return DeploymentResolution(
                route_preview="legacy_runner",
                reason="direct_route_requirements_not_met:" + ",".join(blockers),
                live_blocked_reasons=_live_gate_blockers(deployment),
                deployment_id=deployment.deployment_id,
                agent_id=deployment.agent_id,
                active_version_id=deployment.active_version_id,
            )
        return DeploymentResolution(
            route_preview="product_agent_direct",
            reason="published_product_agent_with_respond_style_enabled",
            live_blocked_reasons=_live_gate_blockers(deployment),
            deployment_id=deployment.deployment_id,
            agent_id=deployment.agent_id,
            active_version_id=deployment.active_version_id,
        )


PUBLISHED_STATES: tuple[str, ...] = ("published", "published_no_send")


def _direct_route_blockers(deployment: DeploymentView) -> list[str]:
    blockers: list[str] = []
    if deployment.publish_state not in PUBLISHED_STATES:
        blockers.append("publish_state_not_published")
    if not deployment.respond_style_enabled:
        blockers.append("respond_style_not_enabled")
    if not deployment.active_version_id:
        blockers.append("no_active_version")
    return blockers


def _live_gate_blockers(deployment: DeploymentView) -> list[str]:
    """Live gates that remain closed in this phase regardless of config.
    Listing them keeps the preview honest: a deployment with send flags on
    still resolves no-send here."""
    blockers = ["phase_11_is_no_send_only"]
    if not deployment.send_enabled:
        blockers.append("send_not_enabled")
    if not deployment.outbox_enabled:
        blockers.append("outbox_not_enabled")
    if not deployment.live_send_enabled:
        blockers.append("live_send_not_enabled")
    return blockers


__all__ = [
    "DeploymentResolution",
    "DeploymentView",
    "RespondStyleDeploymentResolver",
]
