from uuid import uuid4

import pytest

from atendia.db.models.product_agent import AgentDeployment
from atendia.product_agents.service import (
    PublishStateTransitionError,
    apply_deployment_state_transition,
    ensure_deployment_send_safety,
)


def test_published_no_send_does_not_enable_live_flags() -> None:
    deployment = AgentDeployment(
        tenant_id=uuid4(),
        agent_id=uuid4(),
        name="Readiness",
        publish_state="ready_for_approval",
    )

    apply_deployment_state_transition(deployment, to_state="published_no_send")

    assert deployment.send_enabled is None or deployment.send_enabled is False
    assert deployment.outbox_enabled is None or deployment.outbox_enabled is False
    assert deployment.live_send_enabled is None or deployment.live_send_enabled is False
    assert deployment.actions_enabled is None or deployment.actions_enabled is False
    assert deployment.workflow_events_enabled is None or deployment.workflow_events_enabled is False
    assert (
        deployment.workflow_side_effects_enabled is None
        or deployment.workflow_side_effects_enabled is False
    )


def test_deployment_send_safety_rejects_live_flag() -> None:
    deployment = AgentDeployment(
        tenant_id=uuid4(),
        agent_id=uuid4(),
        name="Unsafe",
        publish_state="ready_for_approval",
        live_send_enabled=True,
    )

    with pytest.raises(PublishStateTransitionError):
        ensure_deployment_send_safety(deployment)
