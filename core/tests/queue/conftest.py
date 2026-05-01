import pytest_asyncio
from arq.connections import ArqRedis, RedisSettings, create_pool
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from atendia.config import get_settings


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine(get_settings().database_url)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with Session() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@pytest_asyncio.fixture
async def redis_client():
    client = Redis.from_url(get_settings().redis_url)
    yield client
    await client.aclose()


@pytest_asyncio.fixture
async def arq_redis() -> ArqRedis:
    """An arq-aware Redis pool for enqueueing jobs."""
    pool = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
    yield pool
    await pool.aclose()
