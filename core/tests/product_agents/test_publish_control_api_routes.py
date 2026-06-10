from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from atendia.api import product_agents_routes
from atendia.product_agents.schemas import (
    AgentPublishRequestCreate,
    AgentPublishRequestDecision,
)


class DummySession:
    def __init__(self):
        self.commits = 0
        self.refreshed = []

    async def commit(self):
        self.commits += 1

    async def refresh(self, obj):
        self.refreshed.append(obj)


@pytest.mark.asyncio
async def test_publish_control_routes_delegate_to_service(monkeypatch) -> None:
    tenant_id = uuid4()
    user = SimpleNamespace(user_id=uuid4())
    deployment_id = uuid4()
    request_id = uuid4()
    publish_request = SimpleNamespace(id=request_id, status="ready_for_approval")
    calls = {}

    async def fake_create(_session, **kwargs):
        calls["create"] = kwargs
        return publish_request

    async def fake_latest(_session, **kwargs):
        calls["latest"] = kwargs
        return publish_request

    async def fake_evaluate(_session, **kwargs):
        calls["evaluate"] = kwargs
        return publish_request

    async def fake_approve(_session, **kwargs):
        calls["approve"] = kwargs
        publish_request.status = "approved_no_send"
        return publish_request

    async def fake_reject(_session, **kwargs):
        calls["reject"] = kwargs
        publish_request.status = "rejected"
        return publish_request

    monkeypatch.setattr(product_agents_routes.service, "create_publish_request", fake_create)
    monkeypatch.setattr(product_agents_routes.service, "get_latest_publish_request", fake_latest)
    monkeypatch.setattr(product_agents_routes.service, "evaluate_publish_request", fake_evaluate)
    monkeypatch.setattr(
        product_agents_routes.service,
        "approve_publish_request_no_send",
        fake_approve,
    )
    monkeypatch.setattr(product_agents_routes.service, "reject_publish_request", fake_reject)
    session = DummySession()

    assert (
        await product_agents_routes.create_publish_request(
            deployment_id,
            AgentPublishRequestCreate(agent_version_id=uuid4()),
            tenant_id=tenant_id,
            user=user,
            session=session,
        )
    ) is publish_request
    assert (
        await product_agents_routes.get_latest_publish_request(
            deployment_id,
            tenant_id=tenant_id,
            session=session,
        )
    ) is publish_request
    assert (
        await product_agents_routes.evaluate_publish_request(
            request_id,
            tenant_id=tenant_id,
            session=session,
        )
    ) is publish_request
    assert (
        await product_agents_routes.approve_publish_request_no_send(
            request_id,
            AgentPublishRequestDecision(approval_text="approve no-send"),
            tenant_id=tenant_id,
            user=user,
            session=session,
        )
    ) is publish_request
    assert (
        await product_agents_routes.reject_publish_request(
            request_id,
            AgentPublishRequestDecision(reason="not ready"),
            tenant_id=tenant_id,
            user=user,
            session=session,
        )
    ) is publish_request

    assert session.commits == 4
    assert session.refreshed == [publish_request, publish_request, publish_request, publish_request]
    assert calls["create"]["deployment_id"] == deployment_id
    assert calls["create"]["requested_state"] == "published_no_send"
    assert calls["latest"] == {"tenant_id": tenant_id, "deployment_id": deployment_id}
    assert calls["evaluate"] == {"tenant_id": tenant_id, "request_id": request_id}
    assert calls["approve"]["approval_text"] == "approve no-send"
    assert calls["reject"]["reason"] == "not ready"


@pytest.mark.asyncio
async def test_publish_control_routes_map_service_errors(monkeypatch) -> None:
    async def fake_create(*_args, **_kwargs):
        raise product_agents_routes.service.PublishStateTransitionError("blocked")

    async def fake_latest(*_args, **_kwargs):
        raise product_agents_routes.service.ProductAgentNotFoundError("missing")

    async def fake_evaluate(*_args, **_kwargs):
        raise product_agents_routes.service.ProductAgentError("bad evaluate")

    async def fake_approve(*_args, **_kwargs):
        raise product_agents_routes.service.PublishStateTransitionError("bad approve")

    async def fake_reject(*_args, **_kwargs):
        raise product_agents_routes.service.ProductAgentError("bad reject")

    monkeypatch.setattr(product_agents_routes.service, "create_publish_request", fake_create)
    monkeypatch.setattr(product_agents_routes.service, "get_latest_publish_request", fake_latest)
    monkeypatch.setattr(product_agents_routes.service, "evaluate_publish_request", fake_evaluate)
    monkeypatch.setattr(
        product_agents_routes.service,
        "approve_publish_request_no_send",
        fake_approve,
    )
    monkeypatch.setattr(product_agents_routes.service, "reject_publish_request", fake_reject)

    with pytest.raises(HTTPException) as create_exc:
        await product_agents_routes.create_publish_request(
            uuid4(),
            AgentPublishRequestCreate(agent_version_id=uuid4()),
            tenant_id=uuid4(),
            user=SimpleNamespace(user_id=uuid4()),
            session=DummySession(),
        )
    assert create_exc.value.status_code == 409

    with pytest.raises(HTTPException) as latest_exc:
        await product_agents_routes.get_latest_publish_request(
            uuid4(),
            tenant_id=uuid4(),
            session=DummySession(),
        )
    assert latest_exc.value.status_code == 404

    with pytest.raises(HTTPException) as evaluate_exc:
        await product_agents_routes.evaluate_publish_request(
            uuid4(),
            tenant_id=uuid4(),
            session=DummySession(),
        )
    assert evaluate_exc.value.status_code == 400

    with pytest.raises(HTTPException) as approve_exc:
        await product_agents_routes.approve_publish_request_no_send(
            uuid4(),
            AgentPublishRequestDecision(approval_text="approve"),
            tenant_id=uuid4(),
            user=SimpleNamespace(user_id=uuid4()),
            session=DummySession(),
        )
    assert approve_exc.value.status_code == 409

    with pytest.raises(HTTPException) as reject_exc:
        await product_agents_routes.reject_publish_request(
            uuid4(),
            AgentPublishRequestDecision(reason="bad"),
            tenant_id=uuid4(),
            user=SimpleNamespace(user_id=uuid4()),
            session=DummySession(),
        )
    assert reject_exc.value.status_code == 400
