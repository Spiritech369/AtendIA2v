import asyncio
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from atendia.config import get_settings

_engine = None
_session_factory = None
_engine_loop_id: int | None = None


def _get_factory() -> async_sessionmaker[AsyncSession]:
    global _engine, _session_factory, _engine_loop_id
    current_loop_id = id(asyncio.get_running_loop())
    if _engine is None or _engine_loop_id != current_loop_id:
        _engine = create_async_engine(get_settings().database_url)
        _session_factory = async_sessionmaker(_engine, expire_on_commit=False, class_=AsyncSession)
        _engine_loop_id = current_loop_id
    return _session_factory  # type: ignore[return-value]


async def get_db_session() -> AsyncIterator[AsyncSession]:
    factory = _get_factory()
    async with factory() as session:
        yield session
