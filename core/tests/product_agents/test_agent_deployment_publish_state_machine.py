from uuid import uuid4

import pytest

from atendia.db.models.product_agent import AgentDeployment
from atendia.product_agents.service import (
    PublishStateTransitionError,
    apply_deployment_state_transition,
    validate_publish_state_transition,
)


def test_agent_deployment_state_machine_allows_no_send_publish_path() -> None:
    validate_publish_state_transition("draft", "test_required")
    validate_publish_state_transition("test_required", "test_passed")
    validate_publish_state_transition("test_passed", "ready_for_approval")
    validate_publish_state_transition("ready_for_approval", "published_no_send")


def test_agent_deployment_state_machine_blocks_live_publish_states() -> None:
    with pytest.raises(PublishStateTransitionError):
        validate_publish_state_transition("ready_for_approval", "production")
    with pytest.raises(PublishStateTransitionError):
        validate_publish_state_transition("ready_for_approval", "published_live_limited")


def test_agent_deployment_state_machine_blocks_unknown_or_invalid_transitions() -> None:
    with pytest.raises(PublishStateTransitionError):
        validate_publish_state_transition("ready_for_approval", "not_a_state")
    with pytest.raises(PublishStateTransitionError):
        validate_publish_state_transition("draft", "published_no_send")


def test_agent_deployment_transition_sets_no_send_runtime_only() -> None:
    deployment = AgentDeployment(
        tenant_id=uuid4(),
        agent_id=uuid4(),
        name="Test Lab",
        publish_state="ready_for_approval",
    )

    apply_deployment_state_transition(deployment, to_state="published_no_send")

    assert deployment.publish_state == "published_no_send"
    assert deployment.runtime_mode == "no_send"
    assert deployment.send_scope == "none"
    assert deployment.send_enabled is None or deployment.send_enabled is False
    assert deployment.outbox_enabled is None or deployment.outbox_enabled is False
    assert deployment.live_send_enabled is None or deployment.live_send_enabled is False
