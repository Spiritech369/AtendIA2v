import pytest_asyncio
from redis.asyncio import Redis

from atendia.config import get_settings


@pytest_asyncio.fixture
async def redis_client():
    client = Redis.from_url(get_settings().redis_url)
    yield client
    await client.aclose()
