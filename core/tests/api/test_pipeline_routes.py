"""Pipeline Kanban (sesión 7).

Coverage:

- Active stages render with their counts + cards (the happy path).
- ``is_stale`` flips to True when ``stage_entered_at`` exceeds the stage's
  ``timeout_hours``.
- A conversation whose ``current_stage`` is not in the active pipeline
  appears in a synthetic ``__orphan__`` group instead of disappearing —
  the loophole flagged in the sesión 1 critique.
- ``/board?assigned_user_id=…`` filters cards to a single operator's
  assignments.
- ``/alerts`` returns only stale cards.
- 404 when the tenant has no active pipeline.
- Cross-tenant isolation: tenant A's board never includes tenant B's rows.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from atendia.config import get_settings

PIPELINE_DEF_THREE_STAGES = json.dumps(
    {
        "stages": [
            {"id": "nuevo", "label": "Nuevo", "timeout_hours": 24},
            {"id": "interesado", "label": "Interesado", "timeout_hours": 1},
            {"id": "cerrado", "label": "Cerrado", "timeout_hours": 0},
        ],
        "docs_per_plan": {"default": ["docs_ine"]},
    }
)


def _seed_pipeline(tenant_id: str, definition: str = PIPELINE_DEF_THREE_STAGES) -> None:
    async def _do() -> None:
        engine = create_async_engine(get_settings().database_url)
        try:
            async with engine.begin() as conn:
                # Ensure no existing active pipeline so our INSERT wins.
                await conn.execute(
                    text("UPDATE tenant_pipelines SET active=false WHERE tenant_id = :t"),
                    {"t": tenant_id},
                )
                await conn.execute(
                    text(
                        "INSERT INTO tenant_pipelines "
                        "(tenant_id, version, definition, active) "
                        "VALUES (:t, 99, :d, true)"
                    ),
                    {"t": tenant_id, "d": definition},
                )
        finally:
            await engine.dispose()

    asyncio.run(_do())


def _seed_conversation(
    tenant_id: str,
    *,
    stage: str,
    stage_entered_hours_ago: float = 0.0,
    assigned_user_id: str | None = None,
) -> str:
    async def _do() -> str:
        engine = create_async_engine(get_settings().database_url)
        try:
            async with engine.begin() as conn:
                cust = (
                    await conn.execute(
                        text(
                            "INSERT INTO customers (tenant_id, phone_e164, name) "
                            "VALUES (:t, :p, 'Cliente') RETURNING id"
                        ),
                        {"t": tenant_id, "p": f"+5215{uuid4().hex[:9]}"},
                    )
                ).scalar()
                conv = (
                    await conn.execute(
                        text(
                            "INSERT INTO conversations "
                            "(tenant_id, customer_id, current_stage, assigned_user_id) "
                            "VALUES (:t, :c, :s, :u) RETURNING id"
                        ),
                        {
                            "t": tenant_id,
                            "c": cust,
                            "s": stage,
                            "u": assigned_user_id,
                        },
                    )
                ).scalar()
                entered = datetime.now(UTC) - timedelta(hours=stage_entered_hours_ago)
                await conn.execute(
                    text(
                        "INSERT INTO conversation_state (conversation_id, stage_entered_at) "
                        "VALUES (:c, :e)"
                    ),
                    {"c": conv, "e": entered},
                )
                return str(conv)
        finally:
            await engine.dispose()

    return asyncio.run(_do())


# ── Happy path ──────────────────────────────────────────────────────


def test_board_groups_by_active_stages(client_tenant_admin) -> None:
    _seed_pipeline(client_tenant_admin.tenant_id)
    _seed_conversation(client_tenant_admin.tenant_id, stage="nuevo")
    _seed_conversation(client_tenant_admin.tenant_id, stage="interesado")
    _seed_conversation(client_tenant_admin.tenant_id, stage="interesado")

    resp = client_tenant_admin.get("/api/v1/pipeline/board")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    by_id = {s["stage_id"]: s for s in body["stages"]}
    assert by_id["nuevo"]["total_count"] == 1
    assert by_id["interesado"]["total_count"] == 2
    assert by_id["cerrado"]["total_count"] == 0
    assert by_id["nuevo"]["timeout_hours"] == 24
    assert by_id["interesado"]["is_orphan"] is False


def test_board_404_when_no_active_pipeline(client_tenant_admin) -> None:
    """Fresh tenant — no pipeline seeded — returns 404."""
    resp = client_tenant_admin.get("/api/v1/pipeline/board")
    assert resp.status_code == 404


# ── Stale detection ─────────────────────────────────────────────────


def test_card_is_stale_after_timeout(client_tenant_admin) -> None:
    _seed_pipeline(client_tenant_admin.tenant_id)
    # ``interesado`` has timeout_hours=1; this card has been there for 5h.
    conv_id = _seed_conversation(
        client_tenant_admin.tenant_id,
        stage="interesado",
        stage_entered_hours_ago=5,
    )
    fresh_id = _seed_conversation(
        client_tenant_admin.tenant_id,
        stage="interesado",
        stage_entered_hours_ago=0.1,
    )
    resp = client_tenant_admin.get("/api/v1/pipeline/board")
    by_id = {s["stage_id"]: s for s in resp.json()["stages"]}
    cards = {c["id"]: c for c in by_id["interesado"]["conversations"]}
    assert cards[conv_id]["is_stale"] is True
    assert cards[fresh_id]["is_stale"] is False


def test_alerts_endpoint_returns_only_stale(client_tenant_admin) -> None:
    _seed_pipeline(client_tenant_admin.tenant_id)
    stale_id = _seed_conversation(
        client_tenant_admin.tenant_id,
        stage="interesado",
        stage_entered_hours_ago=5,
    )
    _seed_conversation(
        client_tenant_admin.tenant_id,
        stage="interesado",
        stage_entered_hours_ago=0.1,
    )
    resp = client_tenant_admin.get("/api/v1/pipeline/alerts")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["id"] == stale_id


def test_cerrado_stage_with_zero_timeout_is_never_stale(client_tenant_admin) -> None:
    """``timeout_hours=0`` is a sentinel for "never alert" (e.g. closed)."""
    _seed_pipeline(client_tenant_admin.tenant_id)
    _seed_conversation(
        client_tenant_admin.tenant_id,
        stage="cerrado",
        stage_entered_hours_ago=999,
    )
    resp = client_tenant_admin.get("/api/v1/pipeline/board")
    by_id = {s["stage_id"]: s for s in resp.json()["stages"]}
    assert all(c["is_stale"] is False for c in by_id["cerrado"]["conversations"])


# ── Orphan detection ────────────────────────────────────────────────


def test_conversation_with_unknown_stage_appears_in_orphan_group(
    client_tenant_admin,
) -> None:
    """Closes the loophole: a conversation whose ``current_stage`` isn't in
    the active pipeline used to disappear from the board entirely."""
    _seed_pipeline(client_tenant_admin.tenant_id)
    orphan_id = _seed_conversation(
        client_tenant_admin.tenant_id,
        stage="ghost_stage_that_existed_before",
    )
    resp = client_tenant_admin.get("/api/v1/pipeline/board")
    body = resp.json()
    orphan_group = next(
        (s for s in body["stages"] if s.get("is_orphan") is True),
        None,
    )
    assert orphan_group is not None
    assert orphan_group["stage_id"] == "__orphan__"
    assert orphan_group["total_count"] == 1
    assert any(c["id"] == orphan_id for c in orphan_group["conversations"])


def test_no_orphan_group_when_all_stages_active(client_tenant_admin) -> None:
    _seed_pipeline(client_tenant_admin.tenant_id)
    _seed_conversation(client_tenant_admin.tenant_id, stage="nuevo")
    resp = client_tenant_admin.get("/api/v1/pipeline/board")
    body = resp.json()
    assert all(not s.get("is_orphan", False) for s in body["stages"])


# ── assigned_user_id filter ────────────────────────────────────────


def test_assigned_user_id_filters_cards(client_tenant_admin) -> None:
    _seed_pipeline(client_tenant_admin.tenant_id)
    own_id = _seed_conversation(
        client_tenant_admin.tenant_id,
        stage="nuevo",
        assigned_user_id=client_tenant_admin.user_id,
    )
    _other_id = _seed_conversation(
        client_tenant_admin.tenant_id,
        stage="nuevo",
        assigned_user_id=None,
    )
    resp = client_tenant_admin.get(
        "/api/v1/pipeline/board",
        params={"assigned_user_id": client_tenant_admin.user_id},
    )
    by_id = {s["stage_id"]: s for s in resp.json()["stages"]}
    cards = by_id["nuevo"]["conversations"]
    assert {c["id"] for c in cards} == {own_id}


# ── Tenant isolation ────────────────────────────────────────────────


def test_board_is_tenant_scoped(client_tenant_admin) -> None:
    """Seed a conversation under the test tenant and verify nothing from
    other tenants appears in the board."""
    _seed_pipeline(client_tenant_admin.tenant_id)
    own_id = _seed_conversation(client_tenant_admin.tenant_id, stage="nuevo")
    resp = client_tenant_admin.get("/api/v1/pipeline/board")
    body = resp.json()
    seen: set[str] = set()
    for s in body["stages"]:
        for c in s["conversations"]:
            seen.add(c["id"])
    # All seen ids must be ours (we only seeded one).
    assert seen == {own_id}


def test_stage_endpoint_supports_offset_pagination(client_tenant_admin) -> None:
    """Sprint C.3 — GET /board/{stage_id}?offset=N&limit=M returns the next
    page. The kanban front-end calls this when the operator clicks
    "Cargar más" on a stage that has more cards than the initial page.

    Order is stable (last_activity_at DESC, id DESC) so paging through
    doesn't reshuffle. ``total_count`` keeps returning the full count
    regardless of offset, so the front-end can hide "Cargar más" once
    `offset + page_size >= total`.
    """
    _seed_pipeline(client_tenant_admin.tenant_id)
    # Seed 5 conversations in 'interesado' so we can ask for offset=2,limit=2.
    ids = [_seed_conversation(client_tenant_admin.tenant_id, stage="interesado") for _ in range(5)]

    page1 = client_tenant_admin.get("/api/v1/pipeline/board/interesado?limit=2&offset=0")
    assert page1.status_code == 200, page1.text
    p1 = page1.json()
    assert p1["total_count"] == 5
    assert len(p1["conversations"]) == 2
    page1_ids = [c["id"] for c in p1["conversations"]]

    page2 = client_tenant_admin.get("/api/v1/pipeline/board/interesado?limit=2&offset=2")
    assert page2.status_code == 200, page2.text
    p2 = page2.json()
    assert p2["total_count"] == 5
    assert len(p2["conversations"]) == 2
    page2_ids = [c["id"] for c in p2["conversations"]]
    # No overlap between pages.
    assert set(page1_ids).isdisjoint(set(page2_ids))

    page3 = client_tenant_admin.get("/api/v1/pipeline/board/interesado?limit=2&offset=4")
    p3 = page3.json()
    assert page3.status_code == 200
    assert len(p3["conversations"]) == 1, "tail page has the last remaining card"
    # Combined coverage: every seeded id surfaced across the 3 pages.
    assert set(page1_ids) | set(page2_ids) | {p3["conversations"][0]["id"]} == set(ids)
