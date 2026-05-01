import json

import pytest
from sqlalchemy import text

from atendia.channels.tenant_config import (
    MetaTenantConfig,
    MetaTenantConfigNotFoundError,
    load_meta_config,
)


@pytest.mark.asyncio
async def test_load_meta_config_returns_struct(db_session):
    config = {
        "meta": {
            "phone_number_id": "1234567890",
            "verify_token": "tenant_verify_secret_xyz",
        }
    }
    tid = (await db_session.execute(
        text("INSERT INTO tenants (name, config) VALUES (:n, :c\\:\\:jsonb) RETURNING id"),
        {"n": "test_t6_meta", "c": json.dumps(config)},
    )).scalar()
    await db_session.commit()

    result = await load_meta_config(db_session, tid)
    assert isinstance(result, MetaTenantConfig)
    assert result.phone_number_id == "1234567890"
    assert result.verify_token == "tenant_verify_secret_xyz"

    await db_session.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tid})
    await db_session.commit()


@pytest.mark.asyncio
async def test_load_meta_config_raises_when_no_meta_section(db_session):
    tid = (await db_session.execute(
        text("INSERT INTO tenants (name, config) VALUES ('test_t6_no_meta', '{}'::jsonb) RETURNING id")
    )).scalar()
    await db_session.commit()

    with pytest.raises(MetaTenantConfigNotFoundError):
        await load_meta_config(db_session, tid)

    await db_session.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tid})
    await db_session.commit()


@pytest.mark.asyncio
async def test_load_meta_config_raises_when_meta_missing_required_keys(db_session):
    """`meta` section exists but doesn't have phone_number_id and verify_token."""
    config = {"meta": {"phone_number_id": "X"}}  # missing verify_token
    tid = (await db_session.execute(
        text("INSERT INTO tenants (name, config) VALUES (:n, :c\\:\\:jsonb) RETURNING id"),
        {"n": "test_t6_partial", "c": json.dumps(config)},
    )).scalar()
    await db_session.commit()

    with pytest.raises(MetaTenantConfigNotFoundError):
        await load_meta_config(db_session, tid)

    await db_session.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tid})
    await db_session.commit()


@pytest.mark.asyncio
async def test_load_meta_config_raises_when_tenant_not_found(db_session):
    from uuid import uuid4
    fake_id = uuid4()
    with pytest.raises(MetaTenantConfigNotFoundError):
        await load_meta_config(db_session, fake_id)
