from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from atendia.product_agents.routing_preview import (
    log_routing_preview_safely,
    preview_respond_style_routing,
)


def _deployment_row(**overrides) -> SimpleNamespace:
    base = {
        "id": uuid4(),
        "tenant_id": uuid4(),
        "agent_id": uuid4(),
        "active_version_id": uuid4(),
        "channel": "whatsapp",
        "environment": "no_send",
        "publish_state": "published",
        "runtime_mode": "test_lab_no_send",
        "send_enabled": True,
        "outbox_enabled": True,
        "live_send_enabled": False,
        "metadata_json": {"respond_style_enabled": True},
    }
    base.update(overrides)
    return SimpleNamespace(**base)


class _FakeSession:
    def __init__(self, rows: list[SimpleNamespace]) -> None:
        self._rows = rows

    async def execute(self, query):
        rows = self._rows

        class _Result:
            def scalars(self):
                return rows

        return _Result()


@pytest.mark.asyncio
async def test_preview_maps_deployments_and_stays_no_send() -> None:
    tenant_id = uuid4()
    rows = [
        _deployment_row(tenant_id=tenant_id),
        _deployment_row(tenant_id=tenant_id, publish_state="draft"),
    ]

    previews = await preview_respond_style_routing(
        _FakeSession(rows),  # type: ignore[arg-type]
        tenant_id=tenant_id,
    )

    assert previews[0]["route_preview"] == "product_agent_direct"
    assert previews[1]["route_preview"] == "legacy_runner"
    assert all(item["send_decision"] == "no_send" for item in previews)
    assert all(item["live_routing_active"] is False for item in previews)


@pytest.mark.asyncio
async def test_log_preview_swallows_all_failures() -> None:
    class _BrokenSession:
        async def execute(self, query):
            raise RuntimeError("db down")

    # Must not raise — the inbound pipeline depends on this guarantee.
    await log_routing_preview_safely(
        _BrokenSession(),  # type: ignore[arg-type]
        tenant_id=uuid4(),
        conversation_id="conv-1",
    )


def test_inbound_wiring_is_log_only() -> None:
    from pathlib import Path

    source = Path("core/atendia/api/baileys_routes.py").read_text(encoding="utf-8")
    assert "log_routing_preview_safely" in source
    # The preview module itself never routes, sends, or enqueues.
    preview_source = Path(
        "core/atendia/product_agents/routing_preview.py"
    ).read_text(encoding="utf-8")
    forbidden = [
        "ConversationRunner",
        "stage_outbound",
        "enqueue_messages",
        "evaluate_event",
        "send_text",
        "ProductAgentRuntime(",
    ]
    assert not any(term in preview_source for term in forbidden)
