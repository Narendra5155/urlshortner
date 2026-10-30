"""Shared fixtures.

All configuration (POSTGRES_*, REDIS_*, BASE_URL, RATE_LIMIT_PER_MINUTE, ...) comes from the
environment / .env, exactly as for the app. Point POSTGRES_DB at a database you don't mind
being emptied: the `links` table is truncated before every integration test. In Redis only
this app's keys (link:*, clicks:*, ratelimit:*) are deleted.

If Postgres or Redis is unreachable, integration tests are skipped and unit tests still run,
unless REQUIRE_SERVICES=1 is set, in which case they fail.
"""

import os
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.config import get_settings
from app.db import Base, SessionLocal, engine
from app.main import app
from app.redis_client import get_redis

APP_KEY_PATTERNS = ("link:*", "clicks:*", "ratelimit:*")


@pytest_asyncio.fixture(scope="session")
async def services():
    """Check connectivity and create tables once per run; yields a Redis client."""
    test_redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    try:
        await test_redis.ping()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    except (OSError, SQLAlchemyError, RedisError) as exc:
        await test_redis.aclose()
        message = f"Postgres/Redis not reachable for integration tests: {exc}"
        if os.environ.get("REQUIRE_SERVICES") == "1":
            pytest.fail(message, pytrace=False)
        pytest.skip(message)

    yield test_redis
    await test_redis.aclose()
    await engine.dispose()


@pytest_asyncio.fixture
async def test_redis(services) -> Redis:
    """Empty the links table and this app's Redis keys before every test."""
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE links RESTART IDENTITY"))
    for pattern in APP_KEY_PATTERNS:
        keys = [key async for key in services.scan_iter(match=pattern)]
        if keys:
            await services.delete(*keys)
    return services


@pytest_asyncio.fixture
async def client(test_redis):
    app.dependency_overrides[get_redis] = lambda: test_redis
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def db_session(test_redis):
    async with SessionLocal() as session:
        yield session


class Clock:
    """Controllable 'now' for the rate limiter's one-minute windows."""

    def __init__(self) -> None:
        self.now = datetime(2026, 1, 1, 12, 0, 30, tzinfo=timezone.utc)

    def advance(self, **delta) -> None:
        self.now += timedelta(**delta)


@pytest.fixture
def frozen_clock(monkeypatch) -> Clock:
    clock = Clock()

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock.now if tz else clock.now.replace(tzinfo=None)

    monkeypatch.setattr("app.services.cache.datetime", FrozenDatetime)
    return clock


@pytest.fixture
def create_link(client):
    async def _create(url: str = "https://example.com/a/long/path", **extra):
        res = await client.post("/api/links", json={"url": url, **extra})
        assert res.status_code == 201, res.text
        return res.json()

    return _create
