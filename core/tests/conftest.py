from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import create_async_engine

CORE_DIR = Path(__file__).resolve().parents[1]
if str(CORE_DIR) not in sys.path:
    sys.path.insert(0, str(CORE_DIR))

TEST_DATABASE_URL_ENV = "ATENDIA_TEST_DATABASE_URL"
APP_DATABASE_URL_ENV = "ATENDIA_V2_DATABASE_URL"

if os.environ.get(TEST_DATABASE_URL_ENV):
    os.environ[APP_DATABASE_URL_ENV] = os.environ[TEST_DATABASE_URL_ENV]


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "integration_db: tests that require a migrated PostgreSQL test database",
    )


@pytest.fixture(scope="session", autouse=True)
def _integration_db_session_harness(request: pytest.FixtureRequest) -> None:
    if not _selected_integration_db_items(request):
        return
    test_url = os.environ.get(TEST_DATABASE_URL_ENV)
    if not test_url:
        pytest.exit(
            "integration_db tests require ATENDIA_TEST_DATABASE_URL. "
            "Start PostgreSQL with `docker compose -f docker-compose.test.yml up -d postgres-test` "
            "and export ATENDIA_TEST_DATABASE_URL="
            "postgresql+asyncpg://atendia:atendia@localhost:55432/atendia_test.",
            returncode=2,
        )
    os.environ[APP_DATABASE_URL_ENV] = test_url
    _clear_settings_cache()
    _verify_test_db_reachable(test_url)
    _run_migrations()


@pytest.fixture(autouse=True)
def _integration_db_clean_tables(request: pytest.FixtureRequest) -> None:
    if request.node.get_closest_marker("integration_db") is None:
        yield
        return
    test_url = os.environ.get(TEST_DATABASE_URL_ENV)
    if not test_url:
        yield
        return
    _truncate_application_tables(test_url)
    yield
    _truncate_application_tables(test_url)


def _selected_integration_db_items(request: pytest.FixtureRequest) -> bool:
    return any(
        item.get_closest_marker("integration_db") is not None
        for item in request.session.items
    )


def _verify_test_db_reachable(test_url: str) -> None:
    async def _probe() -> None:
        engine = create_async_engine(test_url)
        try:
            async with engine.begin() as conn:
                await conn.execute(text("SELECT 1"))
        finally:
            await engine.dispose()

    try:
        asyncio.run(_probe())
    except SQLAlchemyError as exc:
        pytest.exit(
            "integration_db tests could not connect to ATENDIA_TEST_DATABASE_URL. "
            f"Configured URL: {test_url}. Original error: {type(exc).__name__}: {exc}",
            returncode=2,
        )


def _run_migrations() -> None:
    alembic_cfg = Config(str(CORE_DIR / "alembic.ini"))
    command.upgrade(alembic_cfg, "head")


def _truncate_application_tables(test_url: str) -> None:
    async def _truncate() -> None:
        engine = create_async_engine(test_url)
        try:
            async with engine.begin() as conn:
                table_names = (
                    await conn.execute(
                        text(
                            "SELECT tablename FROM pg_tables "
                            "WHERE schemaname = 'public' "
                            "AND tablename <> 'alembic_version' "
                            "ORDER BY tablename"
                        )
                    )
                ).scalars().all()
                if table_names:
                    quoted = ", ".join(f'public."{name}"' for name in table_names)
                    await conn.execute(text(f"TRUNCATE {quoted} RESTART IDENTITY CASCADE"))
        finally:
            await engine.dispose()

    asyncio.run(_truncate())


def _clear_settings_cache() -> None:
    try:
        from atendia.config import get_settings
        from atendia.db import session as db_session

        get_settings.cache_clear()
        db_session._engine = None
        db_session._session_factory = None
        db_session._engine_loop_id = None
    except Exception:
        return
