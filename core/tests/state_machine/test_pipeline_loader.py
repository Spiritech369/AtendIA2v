import json

import pytest
from sqlalchemy import text

from atendia.state_machine.pipeline_loader import PipelineNotFoundError, load_active_pipeline


@pytest.mark.asyncio
async def test_load_active_pipeline_returns_validated_definition(db_session):
    res = await db_session.execute(
        text("INSERT INTO tenants (name) VALUES ('test_loader_tenant') RETURNING id")
    )
    tenant_id = res.scalar()

    definition = {
        "version": 1,
        "stages": [
            {"id": "greeting", "actions_allowed": ["greet"], "transitions": [{"to": "qualify", "when": "true"}]},
            {"id": "qualify", "required_fields": ["nombre"], "actions_allowed": ["ask_field"], "transitions": []},
        ],
        "tone": {"register": "informal_mexicano"},
        "fallback": "escalate_to_human",
    }
    await db_session.execute(
        text("""
            INSERT INTO tenant_pipelines (tenant_id, version, definition, active)
            VALUES (:tid, 1, :def\\:\\:jsonb, true)
        """),
        {"tid": tenant_id, "def": json.dumps(definition)},
    )
    await db_session.commit()

    p = await load_active_pipeline(db_session, tenant_id)
    assert len(p.stages) == 2
    assert p.stages[0].id == "greeting"

    # cleanup
    await db_session.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tenant_id})
    await db_session.commit()


@pytest.mark.asyncio
async def test_load_active_pipeline_raises_when_none_active(db_session):
    res = await db_session.execute(
        text("INSERT INTO tenants (name) VALUES ('test_no_pipeline') RETURNING id")
    )
    tenant_id = res.scalar()
    await db_session.commit()

    with pytest.raises(PipelineNotFoundError):
        await load_active_pipeline(db_session, tenant_id)

    await db_session.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tenant_id})
    await db_session.commit()
