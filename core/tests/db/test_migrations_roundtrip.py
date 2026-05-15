import asyncio

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine

from atendia.config import get_settings


def _alembic_cfg() -> Config:
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", get_settings().database_url)
    return cfg


@pytest.mark.asyncio
async def test_full_roundtrip_drops_and_recreates_all_tables():
    expected_tables = {
        "tenants",
        "tenant_users",
        "customers",
        "conversations",
        "conversation_state",
        "messages",
        "events",
        "turn_traces",
        "tool_calls",
        "tenant_pipelines",
        "tenant_catalogs",
        "tenant_faqs",
        "tenant_templates_meta",
        "tenant_tools_config",
        "tenant_branding",
        "followups_scheduled",
        "human_handoffs",
        "conversation_reads",
        "notifications",
        "appointments",
        "knowledge_documents",
        "knowledge_chunks",
        "agents",
        "workflows",
        "workflow_executions",
        "workflow_action_runs",
        "workflow_event_cursors",
        "alembic_version",
    }

    cfg = _alembic_cfg()

    await asyncio.to_thread(command.downgrade, cfg, "base")
    await asyncio.to_thread(command.upgrade, cfg, "head")

    engine = create_async_engine(get_settings().database_url)
    async with engine.connect() as conn:

        def _names(sync_conn):
            return set(inspect(sync_conn).get_table_names())

        names = await conn.run_sync(_names)

    await engine.dispose()
    missing = expected_tables - names
    assert not missing, f"missing tables after upgrade: {missing}"
