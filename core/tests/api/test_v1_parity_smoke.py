from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from atendia.config import get_settings


def _seed_customer_conversation(tenant_id: str) -> tuple[str, str]:
    async def _do() -> tuple[str, str]:
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            customer_id = (
                await conn.execute(
                    text(
                        "INSERT INTO customers (tenant_id, phone_e164, name) "
                        "VALUES (:t, :p, 'Ana') RETURNING id"
                    ),
                    {"t": tenant_id, "p": f"+52155{uuid4().hex[:8]}"},
                )
            ).scalar()
            conv_id = (
                await conn.execute(
                    text(
                        "INSERT INTO conversations (tenant_id, customer_id, current_stage) "
                        "VALUES (:t, :c, 'lead') RETURNING id"
                    ),
                    {"t": tenant_id, "c": customer_id},
                )
            ).scalar()
            await conn.execute(
                text("INSERT INTO conversation_state (conversation_id) VALUES (:c)"),
                {"c": conv_id},
            )
            await conn.execute(
                text(
                    "INSERT INTO tenant_pipelines (tenant_id, version, definition, active) "
                    "VALUES (:t, 1, :d, true)"
                ),
                {
                    "t": tenant_id,
                    "d": '{"stages":[{"id":"lead","label":"Lead","timeout_hours":1},{"id":"won","label":"Won","timeout_hours":24}],"docs_per_plan":{"default":["docs_ine"]}}',
                },
            )
        await engine.dispose()
        return str(customer_id), str(conv_id)

    return asyncio.run(_do())


def test_appointments_dashboard_pipeline_and_notifications(client_tenant_admin):
    customer_id, conv_id = _seed_customer_conversation(client_tenant_admin.tenant_id)

    scheduled_at = (datetime.now(UTC) + timedelta(hours=2)).isoformat()
    created = client_tenant_admin.post(
        "/api/v1/appointments",
        json={
            "customer_id": customer_id,
            "conversation_id": conv_id,
            "scheduled_at": scheduled_at,
            "service": "Prueba de manejo",
        },
    )
    assert created.status_code == 201, created.text
    # Sesión 8: create now wraps the appointment + conflicts; the tab-level
    # "id" is on .appointment.
    body = created.json()
    appointment_id = body["appointment"]["id"] if "appointment" in body else body["id"]
    assert body.get("conflicts", []) == []

    assert client_tenant_admin.get("/api/v1/appointments").json()["items"][0]["id"] == appointment_id
    assert client_tenant_admin.patch(f"/api/v1/appointments/{appointment_id}", json={"status": "completed"}).status_code == 200
    assert client_tenant_admin.get("/api/v1/dashboard/summary").status_code == 200

    board = client_tenant_admin.get("/api/v1/pipeline/board")
    assert board.status_code == 200, board.text
    assert board.json()["stages"][0]["stage_id"] == "lead"

    async def _notify() -> None:
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO notifications (tenant_id, user_id, title) "
                    "VALUES (:t, :u, 'Aviso')"
                ),
                {"t": client_tenant_admin.tenant_id, "u": client_tenant_admin.user_id},
            )
        await engine.dispose()

    asyncio.run(_notify())
    notifications = client_tenant_admin.get("/api/v1/notifications")
    assert notifications.status_code == 200
    assert notifications.json()["unread_count"] == 1


def test_knowledge_agents_and_workflows_smoke(client_tenant_admin):
    faq = client_tenant_admin.post(
        "/api/v1/knowledge/faqs",
        json={"question": "Horario?", "answer": "Abrimos de lunes a viernes.", "tags": ["ventas"]},
    )
    assert faq.status_code == 201, faq.text
    assert client_tenant_admin.post("/api/v1/knowledge/test", json={"query": "Horario"}).status_code == 200

    agent = client_tenant_admin.post(
        "/api/v1/agents",
        json={"name": "Ventas", "role": "sales", "is_default": True, "active_intents": ["GREETING"]},
    )
    assert agent.status_code == 201, agent.text
    assert client_tenant_admin.post(
        "/api/v1/agents/test",
        json={"agent_config": agent.json(), "message": "hola"},
    ).status_code == 200

    workflow = client_tenant_admin.post(
        "/api/v1/workflows",
        json={
            "name": "Avisar",
            "trigger_type": "message_received",
            "trigger_config": {},
            "definition": {
                "nodes": [
                    {"id": "trigger_1", "type": "trigger", "config": {}},
                    {"id": "action_1", "type": "notify_agent", "config": {"role": "tenant_admin", "title": "Lead"}},
                ],
                "edges": [{"from": "trigger_1", "to": "action_1"}],
            },
        },
    )
    assert workflow.status_code == 201, workflow.text
    workflow_id = workflow.json()["id"]
    assert client_tenant_admin.post(f"/api/v1/workflows/{workflow_id}/toggle").json()["active"] is True
    assert client_tenant_admin.get(f"/api/v1/workflows/{workflow_id}/executions").status_code == 200
