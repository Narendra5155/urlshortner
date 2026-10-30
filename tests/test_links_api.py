"""/api/links and /api/health endpoint tests."""

from datetime import datetime, timedelta, timezone

import pytest

from app.config import get_settings

pytestmark = pytest.mark.integration


async def test_health(client):
    res = await client.get("/api/health")
    assert res.status_code == 200
    assert res.json() == {"postgres": "ok", "redis": "ok"}


class TestCreate:
    async def test_creates_random_code(self, client):
        res = await client.post("/api/links", json={"url": "https://example.com/some/long/path"})
        assert res.status_code == 201
        body = res.json()
        assert len(body["code"]) == 7
        assert body["target_url"] == "https://example.com/some/long/path"
        assert body["short_url"] == f"{get_settings().base_url.rstrip('/')}/{body['code']}"
        assert body["clicks"] == 0
        assert body["expires_at"] is None
        assert body["last_clicked_at"] is None

    async def test_custom_alias_and_expiry(self, create_link):
        before = datetime.now(timezone.utc)
        body = await create_link(custom_alias="spring-sale", expires_in_days=7)
        assert body["code"] == "spring-sale"
        expires = datetime.fromisoformat(body["expires_at"])
        assert before + timedelta(days=7) <= expires <= datetime.now(timezone.utc) + timedelta(days=7)

    async def test_new_link_is_cached(self, create_link, test_redis):
        body = await create_link()
        assert await test_redis.exists(f"link:{body['code']}") == 1

    async def test_duplicate_alias_conflicts(self, client, create_link):
        await create_link(custom_alias="taken")
        res = await client.post("/api/links", json={"url": "https://other.com", "custom_alias": "taken"})
        assert res.status_code == 409
        assert res.json()["detail"] == "That alias is already taken."

    @pytest.mark.parametrize("alias", ["api", "docs", "API", "redoc"])
    async def test_reserved_alias_conflicts(self, client, alias):
        res = await client.post("/api/links", json={"url": "https://example.com", "custom_alias": alias})
        assert res.status_code == 409
        assert res.json()["detail"] == "That alias is reserved."

    @pytest.mark.parametrize(
        "payload",
        [
            {},
            {"url": "not a url"},
            {"url": "https://example.com", "custom_alias": "a b"},
            {"url": "https://example.com", "custom_alias": "xy"},
            {"url": "https://example.com", "expires_in_days": 0},
            {"url": "https://example.com", "expires_in_days": 400},
        ],
    )
    async def test_invalid_payload(self, client, payload):
        res = await client.post("/api/links", json=payload)
        assert res.status_code == 422

    async def test_retries_on_code_collision(self, client, create_link, monkeypatch):
        await create_link(custom_alias="dupe123")
        codes = iter(["dupe123", "fresh01"])
        monkeypatch.setattr("app.routers.links.generate_code", lambda: next(codes))
        res = await client.post("/api/links", json={"url": "https://example.com"})
        assert res.status_code == 201
        assert res.json()["code"] == "fresh01"

    async def test_gives_up_after_repeated_collisions(self, client, create_link, monkeypatch):
        await create_link(custom_alias="dupe123")
        monkeypatch.setattr("app.routers.links.generate_code", lambda: "dupe123")
        res = await client.post("/api/links", json={"url": "https://example.com"})
        assert res.status_code == 500

    async def test_rate_limited(self, client, frozen_clock):
        limit = get_settings().rate_limit_per_minute
        statuses = [
            (await client.post("/api/links", json={"url": "https://example.com"})).status_code
            for _ in range(limit + 1)
        ]
        assert statuses == [201] * limit + [429]

        frozen_clock.advance(minutes=1)
        res = await client.post("/api/links", json={"url": "https://example.com"})
        assert res.status_code == 201


class TestList:
    async def test_empty(self, client):
        res = await client.get("/api/links")
        assert res.status_code == 200
        assert res.json() == {"items": [], "total": 0}

    async def test_newest_first_with_pagination(self, client, create_link):
        for alias in ["first", "second", "third"]:
            await create_link(custom_alias=alias)

        page1 = (await client.get("/api/links", params={"limit": 2})).json()
        assert page1["total"] == 3
        assert [l["code"] for l in page1["items"]] == ["third", "second"]

        page2 = (await client.get("/api/links", params={"limit": 2, "offset": 2})).json()
        assert [l["code"] for l in page2["items"]] == ["first"]

    @pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 101}, {"offset": -1}])
    async def test_invalid_paging(self, client, params):
        res = await client.get("/api/links", params=params)
        assert res.status_code == 422


class TestGetAndDelete:
    async def test_get_link(self, client, create_link):
        created = await create_link(custom_alias="mine")
        res = await client.get("/api/links/mine")
        assert res.status_code == 200
        assert res.json() == created

    async def test_get_unknown(self, client):
        res = await client.get("/api/links/missing")
        assert res.status_code == 404

    async def test_delete_removes_row_and_cache(self, client, create_link, test_redis):
        await create_link(custom_alias="bye")
        await client.get("/bye")  # creates a clicks:bye counter too
        assert await test_redis.exists("link:bye", "clicks:bye") == 2

        res = await client.delete("/api/links/bye")
        assert res.status_code == 204
        assert await test_redis.exists("link:bye", "clicks:bye") == 0
        assert (await client.get("/api/links/bye")).status_code == 404
        assert (await client.get("/bye")).status_code == 404

    async def test_delete_unknown(self, client):
        res = await client.delete("/api/links/missing")
        assert res.status_code == 404
