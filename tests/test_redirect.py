"""GET/HEAD /{code} redirect tests."""

import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import update

from app.models import Link

pytestmark = pytest.mark.integration


async def test_redirects_to_target(client, create_link):
    link = await create_link("https://example.com/landing?ref=1")
    res = await client.get(f"/{link['code']}")
    assert res.status_code == 307
    assert res.headers["location"] == "https://example.com/landing?ref=1"


async def test_unknown_code(client):
    res = await client.get("/doesnotexist")
    assert res.status_code == 404
    assert res.json()["detail"] == "Link not found."


async def test_get_counts_clicks(client, create_link, test_redis):
    link = await create_link()
    for _ in range(3):
        await client.get(f"/{link['code']}")

    stats = (await client.get(f"/api/links/{link['code']}")).json()
    assert stats["clicks"] == 3
    assert stats["last_clicked_at"] is not None
    assert await test_redis.get(f"clicks:{link['code']}") == "3"


async def test_head_redirects_without_counting(client, create_link, test_redis):
    link = await create_link()
    res = await client.head(f"/{link['code']}")
    assert res.status_code == 307
    assert res.headers["location"] == link["target_url"]

    stats = (await client.get(f"/api/links/{link['code']}")).json()
    assert stats["clicks"] == 0
    assert await test_redis.get(f"clicks:{link['code']}") is None


async def test_serves_from_cache(client, create_link, db_session):
    link = await create_link("https://old.example.com/")
    await db_session.execute(
        update(Link).where(Link.code == link["code"]).values(target_url="https://new.example.com/")
    )
    await db_session.commit()

    res = await client.get(f"/{link['code']}")
    assert res.headers["location"] == "https://old.example.com/"


async def test_cache_miss_reads_postgres_and_recaches(client, create_link, test_redis):
    link = await create_link("https://example.com/")
    await test_redis.delete(f"link:{link['code']}")

    res = await client.get(f"/{link['code']}")
    assert res.status_code == 307
    assert res.headers["location"] == "https://example.com/"
    assert await test_redis.exists(f"link:{link['code']}") == 1


async def test_expired_link_from_postgres(client, db_session, test_redis):
    db_session.add(
        Link(
            code="expired",
            target_url="https://example.com/",
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
    )
    await db_session.commit()

    res = await client.get("/expired")
    assert res.status_code == 410
    assert res.json()["detail"] == "This link has expired."
    assert await test_redis.exists("link:expired") == 0


async def test_expired_link_from_cache(client, create_link, test_redis):
    link = await create_link(expires_in_days=1)
    past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    await test_redis.set(
        f"link:{link['code']}", json.dumps({"target_url": link["target_url"], "expires_at": past})
    )

    res = await client.get(f"/{link['code']}")
    assert res.status_code == 410
    stats = (await client.get(f"/api/links/{link['code']}")).json()
    assert stats["clicks"] == 0


@pytest.mark.parametrize("path", ["/docs", "/openapi.json", "/api/health"])
async def test_app_routes_are_not_shadowed(client, path):
    res = await client.get(path)
    assert res.status_code == 200
