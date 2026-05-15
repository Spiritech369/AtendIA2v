import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from atendia.config import get_settings
from atendia.main import app


def _sync_engine():
    # Convert async URL to sync for setup/cleanup
    url = get_settings().database_url.replace("+asyncpg", "+psycopg")
    return create_engine(url)


@pytest.fixture
def setup_tenant_and_pipeline():
    """Create a tenant + conversation with a 2-turn fixture pipeline."""
    pipeline_def = {
        "version": 1,
        "stages": [
            {
                "id": "qualify",
                "required_fields": ["interes_producto", "ciudad"],
                "actions_allowed": ["ask_field", "lookup_faq", "ask_clarification"],
                "transitions": [
                    {"to": "quote", "when": "all_required_fields_present AND intent == ask_price"},
                ],
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

    # Use a regular sync connection just for fixture setup
    import asyncio
    from sqlalchemy.ext.asyncio import create_async_engine

    async def _setup():
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            tid = (
                await conn.execute(
                    text("INSERT INTO tenants (name) VALUES ('test_t38_api') RETURNING id")
                )
            ).scalar()
            await conn.execute(
                text(
                    "INSERT INTO tenant_pipelines (tenant_id, version, definition, active) "
                    "VALUES (:t, 1, :d\\:\\:jsonb, true)"
                ),
                {"t": tid, "d": json.dumps(pipeline_def)},
            )
            cid = (
                await conn.execute(
                    text(
                        "INSERT INTO customers (tenant_id, phone_e164) VALUES (:t, '+5215555550038') RETURNING id"
                    ),
                    {"t": tid},
                )
            ).scalar()
            conv_id = (
                await conn.execute(
                    text(
                        "INSERT INTO conversations (tenant_id, customer_id, current_stage) "
                        "VALUES (:t, :c, 'qualify') RETURNING id"
                    ),
                    {"t": tid, "c": cid},
                )
            ).scalar()
            await conn.execute(
                text("INSERT INTO conversation_state (conversation_id) VALUES (:c)"),
                {"c": conv_id},
            )
        await engine.dispose()
        return tid, conv_id

    async def _cleanup(tid):
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tid})
        await engine.dispose()

    tid, conv_id = asyncio.run(_setup())
    yield tid, conv_id
    asyncio.run(_cleanup(tid))


def test_health_endpoint():
    with TestClient(app) as client:
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}


def test_run_turn_endpoint_returns_next_stage(setup_tenant_and_pipeline, tmp_path):
    tid, conv_id = setup_tenant_and_pipeline

    fixture = tmp_path / "single_turn.yaml"
    fixture.write_text(
        "nlu_results:\n"
        "  - intent: ask_info\n"
        "    entities:\n"
        "      interes_producto: { value: '150Z', confidence: 0.95, source_turn: 1 }\n"
        "      ciudad: { value: 'CDMX', confidence: 0.95, source_turn: 1 }\n"
        "    sentiment: neutral\n"
        "    confidence: 0.95\n"
        "    ambiguities: []\n"
    )

    with TestClient(app) as client:
        r = client.post(
            "/api/v1/runner/turn",
            json={
                "conversation_id": str(conv_id),
                "tenant_id": str(tid),
                "text": "info de la 150Z, soy de CDMX",
                "turn_number": 1,
                "fixture_path": str(fixture),
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["next_stage"] == "qualify"
        assert "turn_trace_id" in body


def test_run_turn_endpoint_404_when_fixture_missing(setup_tenant_and_pipeline):
    tid, conv_id = setup_tenant_and_pipeline
    with TestClient(app) as client:
        r = client.post(
            "/api/v1/runner/turn",
            json={
                "conversation_id": str(conv_id),
                "tenant_id": str(tid),
                "text": "test",
                "turn_number": 1,
                "fixture_path": "/nonexistent/path/fixture.yaml",
            },
        )
        assert r.status_code == 404
        assert "fixture not found" in r.json()["detail"]
