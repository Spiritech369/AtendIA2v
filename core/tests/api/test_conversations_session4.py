"""Session-4 closures on the Conversations module.

- ``assigned_agent_name`` joined into list+detail responses (frontend uses
  this to badge the row without a second roundtrip).
- ``customer_fields`` for type ``multiselect`` round-trips a JSON-encoded
  array through ``PUT /api/v1/customers/{id}/field-values`` and reads back
  through ``GET /api/v1/conversations/{id}``.
"""

from __future__ import annotations

import asyncio
import json
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from atendia.config import get_settings


def _seed_tenant_with_agent_and_conv(tenant_id: str) -> tuple[str, str, str]:
    """Returns (agent_id, customer_id, conversation_id) under ``tenant_id``."""

    async def _do() -> tuple[str, str, str]:
        engine = create_async_engine(get_settings().database_url)
        try:
            async with engine.begin() as conn:
                agent_id = (
                    await conn.execute(
                        text(
                            "INSERT INTO agents (tenant_id, name, role) "
                            "VALUES (:t, 'Asesor Galgo', 'sales') RETURNING id"
                        ),
                        {"t": tenant_id},
                    )
                ).scalar()
                cust_id = (
                    await conn.execute(
                        text(
                            "INSERT INTO customers (tenant_id, phone_e164, name) "
                            "VALUES (:t, :p, 'Test Cliente') RETURNING id"
                        ),
                        {"t": tenant_id, "p": f"+5215{uuid4().hex[:9]}"},
                    )
                ).scalar()
                conv_id = (
                    await conn.execute(
                        text(
                            "INSERT INTO conversations "
                            "(tenant_id, customer_id, current_stage, assigned_agent_id) "
                            "VALUES (:t, :c, 'lead', :a) RETURNING id"
                        ),
                        {"t": tenant_id, "c": cust_id, "a": agent_id},
                    )
                ).scalar()
                await conn.execute(
                    text("INSERT INTO conversation_state (conversation_id) VALUES (:c)"),
                    {"c": conv_id},
                )
            return str(agent_id), str(cust_id), str(conv_id)
        finally:
            await engine.dispose()

    return asyncio.run(_do())


def test_list_includes_assigned_agent_name(client_tenant_admin) -> None:
    agent_id, _cust_id, conv_id = _seed_tenant_with_agent_and_conv(
        client_tenant_admin.tenant_id,
    )
    resp = client_tenant_admin.get("/api/v1/conversations")
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    target = next((i for i in items if i["id"] == conv_id), None)
    assert target is not None
    assert target["assigned_agent_id"] == agent_id
    assert target["assigned_agent_name"] == "Asesor Galgo"


def test_detail_includes_assigned_agent_name(client_tenant_admin) -> None:
    _agent_id, _cust_id, conv_id = _seed_tenant_with_agent_and_conv(
        client_tenant_admin.tenant_id,
    )
    resp = client_tenant_admin.get(f"/api/v1/conversations/{conv_id}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["assigned_agent_name"] == "Asesor Galgo"


def test_unassigned_conversation_returns_null_agent_name(client_tenant_admin) -> None:
    """Outer join must not drop rows when ``assigned_agent_id`` is NULL."""

    async def _seed() -> str:
        engine = create_async_engine(get_settings().database_url)
        try:
            async with engine.begin() as conn:
                cust_id = (
                    await conn.execute(
                        text(
                            "INSERT INTO customers (tenant_id, phone_e164, name) "
                            "VALUES (:t, :p, 'Solo') RETURNING id"
                        ),
                        {
                            "t": client_tenant_admin.tenant_id,
                            "p": f"+5215{uuid4().hex[:9]}",
                        },
                    )
                ).scalar()
                conv = (
                    await conn.execute(
                        text(
                            "INSERT INTO conversations "
                            "(tenant_id, customer_id, current_stage) "
                            "VALUES (:t, :c, 'lead') RETURNING id"
                        ),
                        {"t": client_tenant_admin.tenant_id, "c": cust_id},
                    )
                ).scalar()
                await conn.execute(
                    text("INSERT INTO conversation_state (conversation_id) VALUES (:c)"),
                    {"c": conv},
                )
                return str(conv)
        finally:
            await engine.dispose()

    conv_id = asyncio.run(_seed())
    resp = client_tenant_admin.get("/api/v1/conversations")
    items = resp.json()["items"]
    target = next((i for i in items if i["id"] == conv_id), None)
    assert target is not None
    assert target["assigned_agent_id"] is None
    assert target["assigned_agent_name"] is None


def test_multiselect_field_value_round_trips(client_tenant_admin) -> None:
    # Define a multiselect field with explicit choices.
    create = client_tenant_admin.post(
        "/api/v1/customer-fields/definitions",
        json={
            "key": "intereses",
            "label": "Intereses",
            "field_type": "multiselect",
            "field_options": {"choices": ["financiamiento", "contado", "trade-in"]},
        },
    )
    assert create.status_code == 201, create.text

    _agent_id, cust_id, conv_id = _seed_tenant_with_agent_and_conv(
        client_tenant_admin.tenant_id,
    )

    # Write the value (server should canonicalise to JSON-encoded list).
    put = client_tenant_admin.put(
        f"/api/v1/customers/{cust_id}/field-values",
        json={"values": {"intereses": ["financiamiento", "trade-in"]}},
    )
    assert put.status_code in {200, 204}, put.text

    detail = client_tenant_admin.get(f"/api/v1/conversations/{conv_id}")
    assert detail.status_code == 200, detail.text
    fields = detail.json()["customer_fields"]
    intereses = next((f for f in fields if f["key"] == "intereses"), None)
    assert intereses is not None
    assert intereses["field_type"] == "multiselect"
    decoded = json.loads(intereses["value"])
    assert sorted(decoded) == ["financiamiento", "trade-in"]
