from __future__ import annotations

import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from atendia.config import get_settings


def _set_demo_tenant(tenant_id: str, is_demo: bool) -> None:
    async def _do() -> None:
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            await conn.execute(
                text("UPDATE tenants SET is_demo = :is_demo WHERE id = :tenant_id"),
                {"is_demo": is_demo, "tenant_id": tenant_id},
            )
        await engine.dispose()

    asyncio.run(_do())


def test_product_config_schema_requires_auth(client):
    resp = client.get("/api/v1/product-config/schema")
    assert resp.status_code == 401


def test_product_config_schema_exposes_minimal_versioned_contract(client_operator):
    resp = client_operator.get("/api/v1/product-config/schema")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["schema_version"] == "2026-05-31.p0"
    assert body["roles_available"] == ["operator", "tenant_admin", "superadmin"]
    assert "manual" in body["pipeline_modes_available"]
    assert "send_message" in body["actions_available"]
    assert "equals" in body["rule_operators_available"]
    assert body["feature_flags"]["show_nyi_controls"] is False


def test_live_tenant_capabilities_default_demo_and_nyi_flags_false(client_operator):
    resp = client_operator.get(f"/api/v1/tenants/{client_operator.tenant_id}/capabilities")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["tenant_id"] == client_operator.tenant_id
    assert body["feature_flags"] == {
        "show_nyi_controls": False,
        "demo_mode": False,
        "mock_knowledge_model": False,
    }
    assert "route.handoffs" in body["current_user"]["capabilities"]
    assert "route.users" not in body["current_user"]["capabilities"]


def test_demo_tenant_capabilities_enable_demo_only_flags(client_operator):
    _set_demo_tenant(client_operator.tenant_id, True)

    resp = client_operator.get(f"/api/v1/tenants/{client_operator.tenant_id}/capabilities")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["feature_flags"]["demo_mode"] is True
    assert body["feature_flags"]["mock_knowledge_model"] is True
    assert body["feature_flags"]["show_nyi_controls"] is False


def test_operator_cannot_read_other_tenant_capabilities(client_operator, tenant_admin_seed):
    other_tenant_id, *_ = tenant_admin_seed

    resp = client_operator.get(f"/api/v1/tenants/{other_tenant_id}/capabilities")

    assert resp.status_code == 403
