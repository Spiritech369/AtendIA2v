from uuid import uuid4

import pytest

from atendia.db.models.product_agent import (
    AgentDeployment,
    AgentPublishRequest,
    AgentTestRun,
    AgentVersion,
)
from atendia.product_agents import service


class FakeResult:
    def __init__(self, scalar=None):
        self._scalar = scalar

    def scalar_one_or_none(self):
        return self._scalar


class FakeSession:
    def __init__(self, *results):
        self.results = list(results)
        self.added = []
        self.flush_count = 0

    async def execute(self, _statement):
        if not self.results:
            raise AssertionError("unexpected execute call")
        return self.results.pop(0)

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        self.flush_count += 1


def _version(tenant_id, agent_id):
    return AgentVersion(
        id=uuid4(),
        tenant_id=tenant_id,
        agent_id=agent_id,
        version_number=1,
        status="draft",
        is_immutable=False,
        role="advisor",
        language="es",
        instructions="Use tenant knowledge.",
    )


def _deployment(tenant_id, agent_id, version_id=None):
    return AgentDeployment(
        id=uuid4(),
        tenant_id=tenant_id,
        agent_id=agent_id,
        active_version_id=version_id,
        name="No-send deployment",
        publish_state="draft",
    )


def _request(tenant_id, agent_id, version_id, deployment_id, rollback_version_id=None):
    return AgentPublishRequest(
        id=uuid4(),
        tenant_id=tenant_id,
        agent_id=agent_id,
        agent_version_id=version_id,
        deployment_id=deployment_id,
        requested_state="published_no_send",
        send_scope="none",
        rollback_version_id=rollback_version_id,
    )


def _passed_run(tenant_id, version_id):
    return AgentTestRun(
        id=uuid4(),
        tenant_id=tenant_id,
        agent_version_id=version_id,
        test_suite_id=uuid4(),
        mode="no_send",
        status="passed",
        decision="TEST_LAB_PASSED",
        trace_ids=["trace-1"],
        outbox_audit_result={"status": "pass", "count": 0},
        side_effect_audit_result={"status": "pass", "count": 0},
        coverage_summary={"execution_mode": "runtime_v2_agent_service"},
    )


def test_publish_request_payload_validation_blocks_live_scope_and_bad_json() -> None:
    service.validate_publish_request_payload(
        requested_state="published_no_send",
        send_scope="none",
        audience_scope={},
    )
    with pytest.raises(service.PublishStateTransitionError, match="published_no_send"):
        service.validate_publish_request_payload(
            requested_state="production",
            send_scope="none",
            audience_scope={},
        )
    with pytest.raises(service.PublishStateTransitionError, match="live send"):
        service.validate_publish_request_payload(
            requested_state="published_no_send",
            send_scope="production",
            audience_scope={},
        )
    with pytest.raises(service.ProductAgentError, match="audience_scope"):
        service.validate_publish_request_payload(
            requested_state="published_no_send",
            send_scope="none",
            audience_scope=[],  # type: ignore[arg-type]
        )


def test_publish_request_blockers_cover_gates_and_test_lab_audits() -> None:
    tenant_id = uuid4()
    agent_id = uuid4()
    version = _version(tenant_id, agent_id)
    deployment = _deployment(tenant_id, agent_id, version_id=uuid4())
    deployment.send_enabled = True
    publish_request = _request(tenant_id, agent_id, version.id, deployment.id)
    failed_run = AgentTestRun(
        tenant_id=tenant_id,
        agent_version_id=version.id,
        test_suite_id=uuid4(),
        status="failed",
        decision="TEST_LAB_FAILED",
        trace_ids=[],
        outbox_audit_result={"status": "block", "count": 1},
        side_effect_audit_result={"status": "block", "count": 1},
        coverage_summary={"execution_mode": "runtime_v2_agent_service"},
    )

    blockers = service._publish_request_blockers(
        publish_request=publish_request,
        deployment=deployment,
        version=version,
        readiness={"blocking_codes": ["required_knowledge_missing"]},
        latest_run=failed_run,
    )

    assert {blocker["code"] for blocker in blockers} == {
        "deployment_version_mismatch",
        "deployment_live_flags_enabled",
        "rollback_target_missing",
        "builder_readiness_blocked",
        "test_lab_not_passed",
        "trace_ids_missing",
        "outbox_audit_not_zero",
        "side_effect_audit_not_zero",
    }


def test_publish_request_blockers_require_runtime_v2_test_lab_mode() -> None:
    tenant_id = uuid4()
    agent_id = uuid4()
    version = _version(tenant_id, agent_id)
    deployment = _deployment(tenant_id, agent_id, version_id=version.id)
    publish_request = _request(tenant_id, agent_id, version.id, deployment.id, uuid4())
    direct_run = _passed_run(tenant_id, version.id)
    direct_run.coverage_summary = {"execution_mode": "openai_direct_provider"}

    blockers = service._publish_request_blockers(
        publish_request=publish_request,
        deployment=deployment,
        version=version,
        readiness={"blocking_codes": []},
        latest_run=direct_run,
    )

    assert "test_lab_runtime_v2_required" in {blocker["code"] for blocker in blockers}


@pytest.mark.asyncio
async def test_create_publish_request_validates_tenant_scope_and_evaluates(monkeypatch) -> None:
    tenant_id = uuid4()
    agent_id = uuid4()
    version = _version(tenant_id, agent_id)
    deployment = _deployment(tenant_id, agent_id)
    rollback = _version(tenant_id, agent_id)

    monkeypatch.setattr(service, "get_deployment_for_tenant", _returns(deployment))
    monkeypatch.setattr(service, "get_agent_version_for_tenant", _sequence(version, rollback))

    async def fake_evaluate(_session, **kwargs):
        created = _session.added[0]
        assert kwargs["request_id"] == created.id
        created.status = service.PUBLISH_REQUEST_STATUS_READY
        return created

    monkeypatch.setattr(service, "evaluate_publish_request", fake_evaluate)
    session = FakeSession()
    created = await service.create_publish_request(
        session,
        tenant_id=tenant_id,
        deployment_id=deployment.id,
        agent_version_id=version.id,
        requested_state="published_no_send",
        send_scope="none",
        channel_scope="test_lab",
        audience_scope={},
        rollback_version_id=rollback.id,
        approval_text="approve no-send",
        requested_by_user_id=uuid4(),
    )

    assert created.status == service.PUBLISH_REQUEST_STATUS_READY
    assert created.agent_id == agent_id
    assert session.added == [created]


@pytest.mark.asyncio
async def test_create_publish_request_rejects_version_from_other_agent(monkeypatch) -> None:
    tenant_id = uuid4()
    deployment = _deployment(tenant_id, uuid4())
    version = _version(tenant_id, uuid4())
    monkeypatch.setattr(service, "get_deployment_for_tenant", _returns(deployment))
    monkeypatch.setattr(service, "get_agent_version_for_tenant", _returns(version))

    with pytest.raises(service.ProductAgentError, match="agent_version_id"):
        await service.create_publish_request(
            FakeSession(),
            tenant_id=tenant_id,
            deployment_id=deployment.id,
            agent_version_id=version.id,
            requested_state="published_no_send",
            send_scope="none",
            channel_scope=None,
            audience_scope={},
            rollback_version_id=None,
            approval_text=None,
            requested_by_user_id=None,
        )


@pytest.mark.asyncio
async def test_create_publish_request_rejects_rollback_from_other_agent(monkeypatch) -> None:
    tenant_id = uuid4()
    agent_id = uuid4()
    deployment = _deployment(tenant_id, agent_id)
    version = _version(tenant_id, agent_id)
    rollback = _version(tenant_id, uuid4())
    monkeypatch.setattr(service, "get_deployment_for_tenant", _returns(deployment))
    monkeypatch.setattr(service, "get_agent_version_for_tenant", _sequence(version, rollback))

    with pytest.raises(service.ProductAgentError, match="rollback_version_id"):
        await service.create_publish_request(
            FakeSession(),
            tenant_id=tenant_id,
            deployment_id=deployment.id,
            agent_version_id=version.id,
            requested_state="published_no_send",
            send_scope="none",
            channel_scope=None,
            audience_scope={},
            rollback_version_id=rollback.id,
            approval_text=None,
            requested_by_user_id=None,
        )


@pytest.mark.asyncio
async def test_get_publish_request_and_latest_are_tenant_scoped() -> None:
    tenant_id = uuid4()
    request = _request(tenant_id, uuid4(), uuid4(), uuid4())
    assert await service.get_publish_request_for_tenant(
        FakeSession(FakeResult(request)),
        tenant_id=tenant_id,
        request_id=request.id,
    ) is request
    with pytest.raises(service.ProductAgentNotFoundError):
        await service.get_publish_request_for_tenant(
            FakeSession(FakeResult(None)),
            tenant_id=tenant_id,
            request_id=uuid4(),
        )

    deployment = _deployment(tenant_id, request.agent_id)
    latest = await service.get_latest_publish_request(
        FakeSession(FakeResult(deployment), FakeResult(request)),
        tenant_id=tenant_id,
        deployment_id=deployment.id,
    )
    assert latest is request


@pytest.mark.asyncio
async def test_latest_test_run_for_version_and_empty_snapshot() -> None:
    tenant_id = uuid4()
    run = _passed_run(tenant_id, uuid4())

    assert await service._latest_test_run_for_version(
        FakeSession(FakeResult(run)),
        tenant_id=tenant_id,
        version_id=run.agent_version_id,
    ) is run
    assert service._test_run_snapshot(None) is None


def test_publish_request_blockers_cover_invalid_request_and_missing_test_lab() -> None:
    tenant_id = uuid4()
    deployment_agent_id = uuid4()
    version = _version(tenant_id, uuid4())
    deployment = _deployment(tenant_id, deployment_agent_id)
    publish_request = _request(tenant_id, deployment_agent_id, version.id, deployment.id, uuid4())
    publish_request.requested_state = "production"
    publish_request.send_scope = "approved_contact_only"

    blockers = service._publish_request_blockers(
        publish_request=publish_request,
        deployment=deployment,
        version=version,
        readiness={"blocking_codes": []},
        latest_run=None,
    )

    assert {blocker["code"] for blocker in blockers} == {
        "requested_state_not_allowed",
        "send_scope_not_allowed",
        "version_deployment_agent_mismatch",
        "test_lab_run_missing",
    }


@pytest.mark.asyncio
async def test_evaluate_publish_request_marks_ready_with_test_lab_evidence(monkeypatch) -> None:
    tenant_id = uuid4()
    agent_id = uuid4()
    version = _version(tenant_id, agent_id)
    rollback = _version(tenant_id, agent_id)
    deployment = _deployment(tenant_id, agent_id)
    request = _request(tenant_id, agent_id, version.id, deployment.id, rollback.id)
    run = _passed_run(tenant_id, version.id)
    monkeypatch.setattr(service, "get_publish_request_for_tenant", _returns(request))
    monkeypatch.setattr(service, "get_deployment_for_tenant", _returns(deployment))
    monkeypatch.setattr(service, "get_agent_version_for_tenant", _returns(version))
    monkeypatch.setattr(service, "evaluate_builder_readiness", _returns({"blocking_codes": []}))
    monkeypatch.setattr(service, "_latest_test_run_for_version", _returns(run))

    evaluated = await service.evaluate_publish_request(
        FakeSession(),
        tenant_id=tenant_id,
        request_id=request.id,
    )

    assert evaluated.status == service.PUBLISH_REQUEST_STATUS_READY
    assert evaluated.blockers == []
    assert evaluated.test_run_ids == [str(run.id)]
    assert evaluated.readiness_snapshot["latest_test_run"]["decision"] == "TEST_LAB_PASSED"


@pytest.mark.asyncio
async def test_approve_publish_request_no_send_sets_safe_deployment_and_event(monkeypatch) -> None:
    tenant_id = uuid4()
    agent_id = uuid4()
    version = _version(tenant_id, agent_id)
    rollback = _version(tenant_id, agent_id)
    deployment = _deployment(tenant_id, agent_id)
    request = _request(tenant_id, agent_id, version.id, deployment.id, rollback.id)

    async def fake_evaluate(_session, **_kwargs):
        request.blockers = []
        return request

    monkeypatch.setattr(service, "evaluate_publish_request", fake_evaluate)
    monkeypatch.setattr(service, "get_deployment_for_tenant", _returns(deployment))
    session = FakeSession()
    approved = await service.approve_publish_request_no_send(
        session,
        tenant_id=tenant_id,
        request_id=request.id,
        approved_by_user_id=uuid4(),
        approval_text="approve no-send",
    )

    assert approved.status == service.PUBLISH_REQUEST_STATUS_APPROVED_NO_SEND
    assert deployment.publish_state == service.DEPLOYMENT_STATE_PUBLISHED_NO_SEND
    assert deployment.runtime_mode == "no_send"
    assert deployment.send_scope == "none"
    assert deployment.send_enabled is False
    assert session.added[0].to_state == service.DEPLOYMENT_STATE_PUBLISHED_NO_SEND


@pytest.mark.asyncio
async def test_approve_publish_request_blocks_when_gates_remain(monkeypatch) -> None:
    request = _request(uuid4(), uuid4(), uuid4(), uuid4())
    request.blockers = [{"code": "test_lab_run_missing"}]
    monkeypatch.setattr(service, "evaluate_publish_request", _returns(request))

    with pytest.raises(service.PublishStateTransitionError, match="blocking gates"):
        await service.approve_publish_request_no_send(
            FakeSession(),
            tenant_id=request.tenant_id,
            request_id=request.id,
            approved_by_user_id=None,
            approval_text=None,
        )


@pytest.mark.asyncio
async def test_reject_publish_request_records_decision(monkeypatch) -> None:
    request = _request(uuid4(), uuid4(), uuid4(), uuid4())
    monkeypatch.setattr(service, "get_publish_request_for_tenant", _returns(request))

    rejected = await service.reject_publish_request(
        FakeSession(),
        tenant_id=request.tenant_id,
        request_id=request.id,
        actor_user_id=uuid4(),
        reason="needs review",
    )

    assert rejected.status == service.PUBLISH_REQUEST_STATUS_REJECTED
    assert rejected.decision_reason == "needs review"
    assert rejected.decided_at is not None


def _returns(value):
    async def _inner(*_args, **_kwargs):
        return value

    return _inner


def _sequence(*values):
    items = list(values)

    async def _inner(*_args, **_kwargs):
        if not items:
            raise AssertionError("unexpected call")
        return items.pop(0)

    return _inner
