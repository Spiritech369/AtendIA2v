"""Phase 2 smoke test — drives the full transport chain end-to-end against the local v2 DB + Redis.

Usage (from `core/`):
    uv run python scripts/smoke_test_phase2.py

Sends 3 simulated inbound webhooks, drains the outbound queue, runs the worker
with Meta mocked, and prints a turn-by-turn summary. Cleanup at the end.

Expected: prints the chain transitions and ends with "OK — phase 2 smoke test passed".
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import sys
from uuid import uuid4

import httpx
import respx
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


# Set env BEFORE importing app modules so Settings picks them up.
os.environ.setdefault("ATENDIA_V2_META_APP_SECRET", "smoke_secret_phase2")
os.environ.setdefault("ATENDIA_V2_META_ACCESS_TOKEN", "TOKEN_SMOKE")
os.environ.setdefault("ATENDIA_V2_META_API_VERSION", "v21.0")
os.environ.setdefault("ATENDIA_V2_META_BASE_URL", "https://graph.facebook.com")

from atendia.config import get_settings  # noqa: E402
from atendia.main import app  # noqa: E402
from atendia.queue.worker import send_outbound  # noqa: E402


APP_SECRET = os.environ["ATENDIA_V2_META_APP_SECRET"]


def _sign(body: bytes) -> str:
    return "sha256=" + hmac.new(APP_SECRET.encode("utf-8"), body, hashlib.sha256).hexdigest()


PIPELINE = {
    "version": 1,
    "stages": [
        {
            "id": "greeting",
            "actions_allowed": ["greet"],
            "transitions": [{"to": "qualify", "when": "intent in [ask_info, ask_price]"}],
        },
        {
            "id": "qualify",
            "actions_allowed": ["ask_field", "lookup_faq", "ask_clarification", "quote"],
            "transitions": [{"to": "quote", "when": "intent == ask_price"}],
        },
        {
            "id": "quote",
            "actions_allowed": ["quote", "ask_clarification"],
            "transitions": [],
        },
    ],
    "tone": {"register": "informal_mexicano"},
    "fallback": "escalate_to_human",
}


def _payload(channel_id: str, text_body: str, phone_number_id: str) -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "WABA",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "x",
                                "phone_number_id": phone_number_id,
                            },
                            "messages": [
                                {
                                    "from": "5215555550280",
                                    "id": channel_id,
                                    "timestamp": "1714579200",
                                    "text": {"body": text_body},
                                    "type": "text",
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }


async def _seed_tenant():
    engine = create_async_engine(get_settings().database_url)
    tenant_name = f"smoke_phase2_{uuid4().hex[:8]}"
    phone_number_id = f"PID_{uuid4().hex[:8].upper()}"
    async with engine.begin() as conn:
        tid = (
            await conn.execute(
                text("INSERT INTO tenants (name, config) VALUES (:n, :c\\:\\:jsonb) RETURNING id"),
                {
                    "n": tenant_name,
                    "c": json.dumps(
                        {
                            "meta": {
                                "phone_number_id": phone_number_id,
                                "verify_token": "vt_smoke",
                            },
                        }
                    ),
                },
            )
        ).scalar()
        await conn.execute(
            text(
                "INSERT INTO tenant_pipelines (tenant_id, version, definition, active) "
                "VALUES (:t, 1, :d\\:\\:jsonb, true)"
            ),
            {"t": tid, "d": json.dumps(PIPELINE)},
        )
    await engine.dispose()
    return tid, tenant_name, phone_number_id


async def _redis_clear(channel_id: str):
    from redis.asyncio import Redis

    r = Redis.from_url(get_settings().redis_url)
    await r.delete(f"dedup:{channel_id}")
    await r.aclose()


async def _drain_one_for_tenant(tenant_id: str) -> dict | None:
    """Drain one outbound job for a specific tenant from arq's queue."""
    from redis.asyncio import Redis
    import arq.jobs

    r = Redis.from_url(get_settings().redis_url)
    try:
        for _ in range(40):
            keys = await r.keys("arq:job:out:*")
            for key in keys:
                raw = await r.get(key)
                if raw is None:
                    continue
                try:
                    job = arq.jobs.deserialize_job(raw, deserializer=None)
                except Exception:
                    continue
                msg_dict = job.args[0]
                if msg_dict.get("tenant_id") == str(tenant_id):
                    # Remove the job key so we don't pick it up twice
                    await r.delete(key)
                    return msg_dict
            await asyncio.sleep(0.05)
        return None
    finally:
        await r.aclose()


async def _read_summary(tid):
    engine = create_async_engine(get_settings().database_url)
    async with engine.begin() as conn:
        msgs = (
            await conn.execute(
                text(
                    "SELECT direction, text, channel_message_id, delivery_status FROM messages "
                    "WHERE tenant_id = :t ORDER BY sent_at"
                ),
                {"t": tid},
            )
        ).fetchall()
        traces = (
            await conn.execute(
                text(
                    "SELECT turn_number, state_after FROM turn_traces "
                    "WHERE tenant_id = :t ORDER BY turn_number"
                ),
                {"t": tid},
            )
        ).fetchall()
        events = (
            await conn.execute(
                text("SELECT type FROM events WHERE tenant_id = :t ORDER BY occurred_at"),
                {"t": tid},
            )
        ).fetchall()
    await engine.dispose()
    return msgs, traces, events


async def _cleanup(tid):
    engine = create_async_engine(get_settings().database_url)
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tid})
    await engine.dispose()


TURNS = [
    ("hola buenos días", "greeting"),
    ("info por favor", "ask_info"),
    ("cuánto cuesta?", "ask_price"),
]


async def main() -> int:
    tid, tenant_name, pid = await _seed_tenant()
    print(f"Tenant {tenant_name} ({tid}) seeded with phone_number_id={pid}")

    client = TestClient(app)
    try:
        for i, (text_body, _expected_intent) in enumerate(TURNS, start=1):
            channel_id = f"wamid.SMOKE_{i}_{uuid4().hex[:6]}"
            await _redis_clear(channel_id)
            body = json.dumps(_payload(channel_id, text_body, pid)).encode()
            sig = _sign(body)
            r = client.post(
                f"/webhooks/meta/{tid}",
                content=body,
                headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig},
            )
            if r.status_code != 200:
                print(f"FAIL — webhook {i} returned {r.status_code}: {r.text}")
                return 1

            # Drain the queued outbound and run the worker
            msg_dict = await _drain_one_for_tenant(str(tid))
            if msg_dict is None:
                print(f"FAIL — no outbound job enqueued after webhook {i}")
                return 1

            with respx.mock(base_url="https://graph.facebook.com") as r_mock:
                r_mock.post(f"/v21.0/{pid}/messages").mock(
                    return_value=httpx.Response(
                        200,
                        json={
                            "messaging_product": "whatsapp",
                            "messages": [{"id": f"wamid.OUT_SMOKE_{i}"}],
                        },
                    )
                )
                result = await send_outbound({}, msg_dict)
            print(
                f"Turn {i}: inbound={text_body!r} → outbound action={msg_dict['metadata'].get('action')!r} "
                f"text={msg_dict['text']!r:.80} → status={result['status']}"
            )

        # Print summary
        msgs, traces, events = await _read_summary(tid)
        print(f"\nMessages persisted: {len(msgs)}")
        for direction, txt, cmid, status in msgs:
            short = (txt or "")[:60]
            print(f"  - [{direction}] {short!r} cmid={cmid} status={status}")
        print(f"Turn traces: {len(traces)}")
        for tn, sa in traces:
            print(f"  - turn={tn} stage={sa.get('current_stage')} intent={sa.get('last_intent')}")
        print(f"Events: {len(events)} types={[e[0] for e in events]}")

        # Sanity assertions
        inbound_count = sum(1 for d, *_ in msgs if d == "inbound")
        outbound_count = sum(1 for d, *_ in msgs if d == "outbound")
        if inbound_count != len(TURNS):
            print(f"FAIL — expected {len(TURNS)} inbound rows, got {inbound_count}")
            return 1
        if outbound_count != len(TURNS):
            print(f"FAIL — expected {len(TURNS)} outbound rows, got {outbound_count}")
            return 1
        if len(traces) != len(TURNS):
            print(f"FAIL — expected {len(TURNS)} turn_traces, got {len(traces)}")
            return 1

    finally:
        await _cleanup(tid)
        print(f"Tenant {tenant_name} cleaned up.")

    print("OK — phase 2 smoke test passed")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
