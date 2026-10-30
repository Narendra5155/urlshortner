"""Redis helper tests against the real (test) Redis database."""

from datetime import datetime, timedelta, timezone

import pytest

from app.config import get_settings
from app.services import cache

pytestmark = pytest.mark.integration


async def test_cache_round_trip(test_redis):
    await cache.cache_link(test_redis, "abc", "https://example.com", None)
    assert await cache.get_cached_link(test_redis, "abc") == {
        "target_url": "https://example.com",
        "expires_at": None,
    }
    assert 0 < await test_redis.ttl("link:abc") <= get_settings().cache_ttl_seconds


async def test_missing_key_returns_none(test_redis):
    assert await cache.get_cached_link(test_redis, "nope") is None


async def test_ttl_is_capped_at_link_expiry(test_redis):
    expires = datetime.now(timezone.utc) + timedelta(seconds=90)
    await cache.cache_link(test_redis, "soon", "https://example.com", expires)
    assert 0 < await test_redis.ttl("link:soon") <= 90
    cached = await cache.get_cached_link(test_redis, "soon")
    assert datetime.fromisoformat(cached["expires_at"]) == expires


async def test_expired_link_is_not_cached(test_redis):
    expired = datetime.now(timezone.utc) - timedelta(seconds=1)
    await cache.cache_link(test_redis, "old", "https://example.com", expired)
    assert await test_redis.exists("link:old") == 0


async def test_incr_and_evict(test_redis):
    await cache.cache_link(test_redis, "abc", "https://example.com", None)
    assert await cache.incr_clicks(test_redis, "abc") == 1
    assert await cache.incr_clicks(test_redis, "abc") == 2
    await cache.evict_link(test_redis, "abc")
    assert await test_redis.exists("link:abc", "clicks:abc") == 0


async def test_rate_limit_allows_up_to_limit(test_redis, frozen_clock):
    limit = get_settings().rate_limit_per_minute
    results = [await cache.hit_rate_limit(test_redis, "1.2.3.4") for _ in range(limit + 1)]
    assert results[:limit] == [False] * limit
    assert results[limit] is True


async def test_rate_limit_resets_next_minute(test_redis, frozen_clock):
    limit = get_settings().rate_limit_per_minute
    for _ in range(limit + 1):
        await cache.hit_rate_limit(test_redis, "1.2.3.4")
    frozen_clock.advance(minutes=1)
    assert await cache.hit_rate_limit(test_redis, "1.2.3.4") is False


async def test_rate_limit_window_key_expires(test_redis, frozen_clock):
    await cache.hit_rate_limit(test_redis, "1.2.3.4")
    keys = await test_redis.keys("ratelimit:1.2.3.4:*")
    assert len(keys) == 1
    assert 0 < await test_redis.ttl(keys[0]) <= 60


async def test_rate_limit_is_per_client(test_redis, frozen_clock):
    limit = get_settings().rate_limit_per_minute
    for _ in range(limit + 1):
        await cache.hit_rate_limit(test_redis, "1.1.1.1")
    assert await cache.hit_rate_limit(test_redis, "2.2.2.2") is False
