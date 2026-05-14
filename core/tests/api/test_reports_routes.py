"""Tests for `/api/v1/reports/overview` — the manager dashboard MVP.

Exercises the four headline cards with synthetic data:
* conversations counts today / week / month
* first-response time avg + sample size
* handoff rate vs total
* pipeline funnel cumulative percentages
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from atendia.config import get_settings


def _seed_conversations(tenant_id: str, *, ages_hours: list[int]) -> list[str]:
    """Insert N conversations with `created_at = now() - hours`. Returns ids."""

    async def _do() -> list[str]:
        engine = create_async_engine(get_settings().database_url)
        ids: list[str] = []
        async with engine.begin() as conn:
            customer = (
                await conn.execute(
                    text(
                        "INSERT INTO customers (tenant_id, phone_e164) "
                        "VALUES (:t, :p) RETURNING id"
                    ),
                    {"t": UUID(tenant_id), "p": f"+5215555{uuid4().hex[:6]}"},
                )
            ).scalar()
            for age in ages_hours:
                cid = (
                    await conn.execute(
                        text(
                            "INSERT INTO conversations (tenant_id, customer_id, "
                            "current_stage, created_at, last_activity_at) "
                            "VALUES (:t, :c, :stage, :ts, :ts) RETURNING id"
                        ),
                        {
                            "t": UUID(tenant_id),
                            "c": customer,
                            "stage": "nuevo",
                            "ts": datetime.now(UTC) - timedelta(hours=age),
                        },
                    )
                ).scalar()
                ids.append(str(cid))
        await engine.dispose()
        return ids

    return asyncio.run(_do())


def _seed_messages(
    tenant_id: str,
    conv_id: str,
    *,
    pairs: list[tuple[str, int]],
) -> None:
    """Insert messages for a conversation. `pairs` = [(direction, age_minutes_ago)]."""

    async def _do() -> None:
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            for direction, age_min in pairs:
                await conn.execute(
                    text(
                        "INSERT INTO messages (conversation_id, tenant_id, direction, "
                        "text, sent_at) VALUES (:c, :t, :d, :txt, :ts)"
                    ),
                    {
                        "c": UUID(conv_id),
                        "t": UUID(tenant_id),
                        "d": direction,
                        "txt": f"{direction} test",
                        "ts": datetime.now(UTC) - timedelta(minutes=age_min),
                    },
                )
        await engine.dispose()

    asyncio.run(_do())


def _seed_handoff(tenant_id: str, conv_id: str, *, hours_ago: int) -> None:
    async def _do() -> None:
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO human_handoffs (conversation_id, tenant_id, reason, "
                    "status, requested_at) "
                    "VALUES (:c, :t, 'test', 'open', :ts)"
                ),
                {
                    "c": UUID(conv_id),
                    "t": UUID(tenant_id),
                    "ts": datetime.now(UTC) - timedelta(hours=hours_ago),
                },
            )
        await engine.dispose()

    asyncio.run(_do())


def _seed_pipeline(tenant_id: str, *, stage_ids: list[str]) -> None:
    """Install an active pipeline with the given ordered stage ids."""

    async def _do() -> None:
        engine = create_async_engine(get_settings().database_url)
        stages = [
            {
                "id": sid,
                "label": sid.capitalize(),
                "is_terminal": (i == len(stage_ids) - 1),
            }
            for i, sid in enumerate(stage_ids)
        ]
        import json

        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO tenant_pipelines (tenant_id, version, definition, "
                    "active, history) "
                    "VALUES (:t, 1, CAST(:d AS JSONB), TRUE, '[]'::jsonb) "
                    "ON CONFLICT (tenant_id, version) DO UPDATE "
                    "SET definition = EXCLUDED.definition, active = TRUE"
                ),
                {
                    "t": UUID(tenant_id),
                    "d": json.dumps({"stages": stages}),
                },
            )
        await engine.dispose()

    asyncio.run(_do())


def _move_conversations(*, ids: list[str], to_stage: str) -> None:
    async def _do() -> None:
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            for cid in ids:
                await conn.execute(
                    text(
                        "UPDATE conversations SET current_stage = :s WHERE id = :c"
                    ),
                    {"s": to_stage, "c": UUID(cid)},
                )
        await engine.dispose()

    asyncio.run(_do())


def test_overview_returns_zeros_for_empty_tenant(client_operator):
    resp = client_operator.get("/api/v1/reports/overview")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["conversations"] == {"today": 0, "this_week": 0, "this_month": 0}
    assert body["first_response"]["sample_size"] == 0
    assert body["first_response"]["avg_seconds"] is None
    assert body["handoff"]["handoff_rate_pct"] == 0.0
    assert body["pipeline_funnel"] == []  # no pipeline configured


def test_overview_counts_conversations_by_windows(client_operator):
    tid = client_operator.tenant_id
    # 3 today (within last 6h), 5 this week (1d, 2d ago), 7 this month (~25d ago).
    _seed_conversations(tid, ages_hours=[1, 2, 3])  # today
    _seed_conversations(tid, ages_hours=[26, 50])  # this week (~1d, 2d ago)
    _seed_conversations(tid, ages_hours=[24 * 25] * 2)  # this month (~25d ago)
    resp = client_operator.get("/api/v1/reports/overview").json()
    assert resp["conversations"]["today"] >= 3
    assert resp["conversations"]["this_week"] >= 3
    assert resp["conversations"]["this_month"] >= 5


def test_overview_first_response_avg(client_operator):
    tid = client_operator.tenant_id
    [c1] = _seed_conversations(tid, ages_hours=[2])
    # First inbound 60 min ago, first outbound 55 min ago → 5 min response.
    _seed_messages(tid, c1, pairs=[("inbound", 60), ("outbound", 55)])
    resp = client_operator.get("/api/v1/reports/overview").json()
    assert resp["first_response"]["sample_size"] >= 1
    avg = resp["first_response"]["avg_seconds"]
    assert avg is not None and 250 <= avg <= 350  # ~300s = 5 min ± slack


def test_overview_handoff_rate(client_operator):
    tid = client_operator.tenant_id
    convs = _seed_conversations(tid, ages_hours=[24, 48, 72])
    # Hand off 2 of the 3 conversations within the 30d window.
    _seed_handoff(tid, convs[0], hours_ago=20)
    _seed_handoff(tid, convs[1], hours_ago=40)
    resp = client_operator.get("/api/v1/reports/overview").json()
    handoff = resp["handoff"]
    assert handoff["total_conversations"] >= 3
    assert handoff["handed_off"] >= 2
    assert handoff["handoff_rate_pct"] > 0


def test_overview_funnel_uses_tenant_pipeline(client_operator):
    tid = client_operator.tenant_id
    _seed_pipeline(tid, stage_ids=["nuevo", "contactado", "ganado"])
    [c1, c2, c3] = _seed_conversations(tid, ages_hours=[1, 2, 3])
    _move_conversations(ids=[c1], to_stage="nuevo")
    _move_conversations(ids=[c2], to_stage="contactado")
    _move_conversations(ids=[c3], to_stage="ganado")
    funnel = client_operator.get("/api/v1/reports/overview").json()["pipeline_funnel"]
    assert [s["stage_id"] for s in funnel] == ["nuevo", "contactado", "ganado"]
    # Cumulative reached: 3, 2, 1 (everyone reached "nuevo", 2 reached "contactado", 1 reached "ganado").
    assert funnel[0]["reached_count"] == 3
    assert funnel[1]["reached_count"] == 2
    assert funnel[2]["reached_count"] == 1
    # Current counts: 1, 1, 1.
    assert funnel[0]["current_count"] == 1
    assert funnel[1]["current_count"] == 1
    assert funnel[2]["current_count"] == 1
    # Conversion: 100%, ~66.7%, ~33.3%.
    assert funnel[0]["conversion_pct"] == 100.0
    assert 60.0 < funnel[1]["conversion_pct"] < 70.0
    assert 30.0 < funnel[2]["conversion_pct"] < 40.0


def test_overview_unauthenticated_returns_401():
    from fastapi.testclient import TestClient

    from atendia.main import app

    resp = TestClient(app).get("/api/v1/reports/overview")
    assert resp.status_code == 401
