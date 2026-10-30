import json
from datetime import datetime, timezone

from redis.asyncio import Redis

from app.config import get_settings


def _link_key(code: str) -> str:
    return f"link:{code}"


def _clicks_key(code: str) -> str:
    return f"clicks:{code}"


async def get_cached_link(r: Redis, code: str) -> dict | None:
    raw = await r.get(_link_key(code))
    return json.loads(raw) if raw else None


async def cache_link(r: Redis, code: str, target_url: str, expires_at: datetime | None) -> None:
    ttl = get_settings().cache_ttl_seconds
    if expires_at is not None:
        remaining = int((expires_at - datetime.now(timezone.utc)).total_seconds())
        if remaining <= 0:
            return
        ttl = min(ttl, remaining)
    payload = {
        "target_url": target_url,
        "expires_at": expires_at.isoformat() if expires_at else None,
    }
    await r.set(_link_key(code), json.dumps(payload), ex=ttl)


async def evict_link(r: Redis, code: str) -> None:
    await r.delete(_link_key(code), _clicks_key(code))


async def incr_clicks(r: Redis, code: str) -> int:
    return await r.incr(_clicks_key(code))


async def hit_rate_limit(r: Redis, client_id: str) -> bool:
    """Fixed one-minute window. Returns True when the client is over the limit."""
    window = int(datetime.now(timezone.utc).timestamp() // 60)
    key = f"ratelimit:{client_id}:{window}"
    async with r.pipeline(transaction=True) as pipe:
        pipe.incr(key)
        pipe.expire(key, 60)
        count, _ = await pipe.execute()
    return count > get_settings().rate_limit_per_minute
