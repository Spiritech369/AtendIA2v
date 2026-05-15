import asyncio
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from atendia.config import get_settings
from atendia.main import app


@pytest.fixture
def setup_tenant_with_meta_config():
    async def _setup():
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            tid = (
                await conn.execute(
                    text(
                        "INSERT INTO tenants (name, config) VALUES (:n, :c\\:\\:jsonb) RETURNING id"
                    ),
                    {
                        "n": "test_t12_verify",
                        "c": json.dumps(
                            {
                                "meta": {
                                    "phone_number_id": "PID",
                                    "verify_token": "tenant_verify_xyz",
                                }
                            }
                        ),
                    },
                )
            ).scalar()
        await engine.dispose()
        return tid

    async def _cleanup(tid):
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tid})
        await engine.dispose()

    tid = asyncio.run(_setup())
    yield tid
    asyncio.run(_cleanup(tid))


@pytest.fixture
def setup_tenant_without_meta_config():
    async def _setup():
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            tid = (
                await conn.execute(
                    text(
                        "INSERT INTO tenants (name, config) VALUES ('test_t12_no_meta', '{}'::jsonb) RETURNING id"
                    )
                )
            ).scalar()
        await engine.dispose()
        return tid

    async def _cleanup(tid):
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tid})
        await engine.dispose()

    tid = asyncio.run(_setup())
    yield tid
    asyncio.run(_cleanup(tid))


def test_meta_webhook_verify_returns_challenge_when_token_matches(setup_tenant_with_meta_config):
    tid = setup_tenant_with_meta_config
    with TestClient(app) as client:
        r = client.get(
            f"/webhooks/meta/{tid}",
            params={
                "hub.mode": "subscribe",
                "hub.challenge": "challenge_string_42",
                "hub.verify_token": "tenant_verify_xyz",
            },
        )
        assert r.status_code == 200
        assert r.text == "challenge_string_42"


def test_meta_webhook_verify_403_when_token_mismatch(setup_tenant_with_meta_config):
    tid = setup_tenant_with_meta_config
    with TestClient(app) as client:
        r = client.get(
            f"/webhooks/meta/{tid}",
            params={
                "hub.mode": "subscribe",
                "hub.challenge": "x",
                "hub.verify_token": "WRONG_TOKEN",
            },
        )
        assert r.status_code == 403


def test_meta_webhook_verify_404_when_tenant_has_no_meta_config(setup_tenant_without_meta_config):
    tid = setup_tenant_without_meta_config
    with TestClient(app) as client:
        r = client.get(
            f"/webhooks/meta/{tid}",
            params={
                "hub.mode": "subscribe",
                "hub.challenge": "x",
                "hub.verify_token": "anything",
            },
        )
        assert r.status_code == 404


def test_meta_webhook_verify_400_when_hub_mode_invalid(setup_tenant_with_meta_config):
    tid = setup_tenant_with_meta_config
    with TestClient(app) as client:
        r = client.get(
            f"/webhooks/meta/{tid}",
            params={
                "hub.mode": "unsubscribe",
                "hub.challenge": "x",
                "hub.verify_token": "tenant_verify_xyz",
            },
        )
        assert r.status_code == 400
