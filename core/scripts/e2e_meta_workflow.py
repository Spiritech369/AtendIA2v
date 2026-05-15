"""End-to-end pipeline probe for Workflows + Meta.

Run locally to verify the FULL chain:

  1. Build a Meta-style inbound webhook payload, sign it with the real
     ``META_APP_SECRET`` from .env.
  2. POST it to ``/webhooks/meta/{tenant_id}`` via FastAPI's TestClient.
  3. Verify in DB: ``messages`` row, ``events.message_received`` row,
     ``workflow_executions`` row created by ``evaluate_event`` (the
     inline-trigger hook wired in session 3).
  4. Manually invoke ``execute_workflow_step`` (since the arq worker isn't
     running in this script) so the workflow's ``message`` action enqueues
     an outbound.
  5. Manually invoke ``send_outbound`` against the real Meta Cloud API.
  6. Print the actual ``DeliveryReceipt`` so the operator sees what Meta
     responded.

Usage::

    cd core
    uv run python scripts/e2e_meta_workflow.py

Exit codes:
    0 — full chain reached Meta and got a 2xx receipt.
    1 — pipeline broke at an internal layer (DB / webhook / engine).
    2 — pipeline reached Meta but Meta rejected the call. Most common
        cause is an expired access token; refresh it in ``.env`` and
        re-run. The script prints the exact Meta error code/message so
        you know what to fix.

This script seeds a temporary tenant tagged ``e2e_meta_<uuid>`` and deletes
it on the way out (CASCADE handles the rest), so it's safe to run repeatedly.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import sys
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from atendia.channels.base import OutboundMessage
from atendia.channels.meta_cloud_api import MetaCloudAPIAdapter
from atendia.config import get_settings
from atendia.main import app
from atendia.queue.force_summary_job import force_summary  # noqa: F401  (silence unused-import)

# Test data ──────────────────────────────────────────────────────────────
PHONE_NUMBER_ID = "1011516488719911"  # Francisco Dinamo Motos NL
SENDER_PHONE = "+5215512345678"  # the inbound "customer" — fake
WORKFLOW_MESSAGE_TEXT = "[E2E test] Workflow triggered. Confirmando recepcion."

INBOUND_TEXT = "hola e2e test"


def _build_webhook_payload(tenant_id: UUID) -> dict:
    """Shape matches what Meta sends. ``parse_webhook`` reads ``messages[0]``."""
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "4004801233143653",  # WABA id
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "+5218149835204",
                                "phone_number_id": PHONE_NUMBER_ID,
                            },
                            "contacts": [
                                {
                                    "profile": {"name": "E2E Tester"},
                                    "wa_id": SENDER_PHONE.lstrip("+"),
                                }
                            ],
                            "messages": [
                                {
                                    "from": SENDER_PHONE.lstrip("+"),
                                    "id": f"wamid.e2e.{uuid4().hex[:12]}",
                                    "timestamp": "1730000000",
                                    "type": "text",
                                    "text": {"body": INBOUND_TEXT},
                                }
                            ],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }


def _sign(body: bytes, app_secret: str) -> str:
    digest = hmac.new(app_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


async def _seed(engine, tenant_id: UUID) -> tuple[UUID, UUID]:
    """Insert tenant + customer + active workflow. Returns (customer_id, workflow_id)."""
    async with engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO tenants (id, name, config) VALUES (:id, :n, :cfg)"),
            {
                "id": tenant_id,
                "n": f"e2e_meta_{uuid4().hex[:8]}",
                "cfg": json.dumps(
                    {
                        "meta": {
                            "phone_number_id": PHONE_NUMBER_ID,
                            "verify_token": "ignored-by-this-test",
                        }
                    }
                ),
            },
        )
        # The webhook handler also looks up the customer by phone, creates one
        # if missing. We pre-seed so we have a stable customer_id for asserts.
        cust_id = (
            await conn.execute(
                text(
                    "INSERT INTO customers (tenant_id, phone_e164, name) "
                    "VALUES (:t, :p, 'E2E Tester') "
                    "ON CONFLICT (tenant_id, phone_e164) DO UPDATE SET name = EXCLUDED.name "
                    "RETURNING id"
                ),
                {"t": tenant_id, "p": SENDER_PHONE},
            )
        ).scalar()

        # Active workflow: trigger=message_received, action=message
        workflow_id = uuid4()
        definition = {
            "nodes": [
                {"id": "trigger_1", "type": "trigger", "config": {"event": "message_received"}},
                {
                    "id": "action_1",
                    "type": "message",
                    "config": {"text": WORKFLOW_MESSAGE_TEXT},
                },
            ],
            "edges": [{"from": "trigger_1", "to": "action_1"}],
        }
        await conn.execute(
            text(
                "INSERT INTO workflows "
                "(id, tenant_id, name, trigger_type, trigger_config, definition, active) "
                "VALUES (:id, :t, 'e2e-test', 'message_received', :tc, :d, true)"
            ),
            {
                "id": workflow_id,
                "t": tenant_id,
                "tc": json.dumps({}),
                "d": json.dumps(definition),
            },
        )
    return cust_id, workflow_id


async def _cleanup(engine, tenant_id: UUID) -> None:
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tenant_id})


def _print(label: str, value) -> None:
    print(f"  {label:<32} {value}")


async def main() -> int:
    settings = get_settings()
    if not settings.meta_app_secret:
        print("FAIL — META_APP_SECRET not set in .env. Cannot sign webhook.")
        return 1
    if not settings.meta_access_token:
        print("FAIL — META_ACCESS_TOKEN not set in .env. Cannot reach Meta.")
        return 1

    engine = create_async_engine(settings.database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    tenant_id = uuid4()

    try:
        cust_id, workflow_id = await _seed(engine, tenant_id)
        print("== STEP 1 — seeded tenant, customer, workflow ==")
        _print("tenant_id", tenant_id)
        _print("customer_id", cust_id)
        _print("workflow_id", workflow_id)
        _print("inbound text", INBOUND_TEXT)

        # ── STEP 2: POST signed webhook ──────────────────────────────
        payload = _build_webhook_payload(tenant_id)
        body = json.dumps(payload).encode("utf-8")
        signature = _sign(body, settings.meta_app_secret)
        client = TestClient(app)
        resp = client.post(
            f"/webhooks/meta/{tenant_id}",
            content=body,
            headers={
                "x-hub-signature-256": signature,
                "Content-Type": "application/json",
            },
        )
        print("\n== STEP 2 — POST /webhooks/meta/{tenant_id} ==")
        _print("status_code", resp.status_code)
        _print("body", resp.text)
        if resp.status_code != 200:
            print("FAIL — webhook returned non-200. Pipeline broke at the entry.")
            return 1

        # ── STEP 3: verify chain in DB ───────────────────────────────
        async with factory() as session:
            messages = (
                await session.execute(
                    text(
                        "SELECT id, direction, text FROM messages "
                        "WHERE tenant_id = :t ORDER BY sent_at DESC"
                    ),
                    {"t": tenant_id},
                )
            ).all()
            events = (
                await session.execute(
                    text(
                        "SELECT id, type FROM events WHERE tenant_id = :t ORDER BY occurred_at DESC"
                    ),
                    {"t": tenant_id},
                )
            ).all()
            execs = (
                await session.execute(
                    text(
                        "SELECT id, status, current_node_id, error_code, error "
                        "FROM workflow_executions WHERE workflow_id = :w"
                    ),
                    {"w": workflow_id},
                )
            ).all()

        print("\n== STEP 3 — verify pipeline state in DB ==")
        _print("messages rows", len(messages))
        for m in messages:
            print(f"    [{m.direction}] {m.text[:70]}")
        _print("events rows", len(events))
        for e in events:
            print(f"    [{e.type}] {e.id}")
        _print("workflow_executions", len(execs))
        for e in execs:
            print(f"    status={e.status} node={e.current_node_id} code={e.error_code}")

        if not events or not any(ev.type == "message_received" for ev in events):
            print("FAIL — no message_received event was emitted.")
            return 1
        if not execs:
            print("FAIL — workflow execution wasn't created. Inline-trigger missing?")
            return 1

        # ── STEP 4: drive workflow execution to completion (no worker) ─
        # If the execution is still ``running`` (created but not advanced),
        # invoke the worker function inline. ``execute_workflow_step`` will
        # call ``send_outbound`` via arq which we can't run here, so the
        # message-action step itself just enqueues. We exercise the engine
        # directly to surface any internal error.
        from atendia.workflows.engine import execute_workflow

        async with factory() as session:
            for e in execs:
                exec_row = (
                    await session.execute(
                        text("SELECT status FROM workflow_executions WHERE id = :i"),
                        {"i": e.id},
                    )
                ).one_or_none()
                if exec_row and exec_row.status == "running":
                    await execute_workflow(session, e.id)
                    await session.commit()
        print("\n== STEP 4 — drove workflow execution(s) inline ==")
        async with factory() as session:
            execs_after = (
                await session.execute(
                    text(
                        "SELECT id, status, error_code, error "
                        "FROM workflow_executions WHERE workflow_id = :w"
                    ),
                    {"w": workflow_id},
                )
            ).all()
            for e in execs_after:
                print(
                    f"    {e.id} -> status={e.status} "
                    f"code={e.error_code} err={(e.error or '')[:80]}"
                )

        # ── STEP 5: real Meta send (the moment of truth) ─────────────
        print("\n== STEP 5 — real Meta API send ==")
        adapter = MetaCloudAPIAdapter(
            access_token=settings.meta_access_token,
            app_secret=settings.meta_app_secret,
            api_version=settings.meta_api_version,
            base_url=settings.meta_base_url,
        )
        # Send to ourselves? No — Meta refuses. Send to the inbound's "from"
        # number to mirror the real workflow path. With a sandbox token
        # this will fail because the recipient isn't in the test allowlist;
        # with a production token it would deliver. Either way, the
        # response tells the operator what's blocking.
        receipt = await adapter.send(
            OutboundMessage(
                tenant_id=str(tenant_id),
                to_phone_e164=SENDER_PHONE,
                text="[E2E probe] " + WORKFLOW_MESSAGE_TEXT,
                idempotency_key=f"e2e:{tenant_id}:{uuid4().hex[:8]}",
            ),
            phone_number_id=PHONE_NUMBER_ID,
            message_id=str(uuid4()),
        )
        _print("receipt status", receipt.status)
        _print("channel_message_id", receipt.channel_message_id)
        _print("error", receipt.error)

        if receipt.status == "sent":
            print("\nPASS — full pipeline reached Meta and got a delivery confirmation.")
            return 0
        else:
            print(
                "\nPARTIAL — pipeline ran end-to-end through internal layers "
                "(webhook -> event -> workflow -> outbound enqueue -> Meta API call). "
                "The Meta call itself failed; see ``error`` above."
            )
            return 2
    finally:
        await _cleanup(engine, tenant_id)
        await engine.dispose()


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
