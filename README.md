# URL Shortener API

FastAPI service that shortens URLs. PostgreSQL stores links; Redis caches redirects, counts clicks and rate-limits link creation. Uses your **local** Postgres and Redis (no Docker).

## Setup

```bash
brew services start postgresql@14
brew services start redis
# create the role and database named in .env, e.g.
psql -d postgres -c "CREATE ROLE shorturl LOGIN PASSWORD 'change-me';"
createdb -O shorturl url_shortner

cp .env.example .env   # then set POSTGRES_PASSWORD
uv sync
uv run uvicorn app.main:app --reload --port 8001
```

The connection URLs are built from the `POSTGRES_*` and `REDIS_*` variables in `app/config.py`. Tables are created automatically on startup. Interactive docs: http://localhost:8001/docs

> Port 8001 is used because 8000 is commonly taken by other local dev servers (e.g. Django).

## Tests

The easiest way: `./scripts/run-tests.sh` sets test env vars, starts throwaway Postgres + Redis containers from `docker-compose.test.yml` (ports 55432/56379, separate compose project, in-memory data), runs pytest and tears the containers down. Extra args go to pytest (`./scripts/run-tests.sh -k redirect -x`); `KEEP_CONTAINERS=1` leaves them running.

To run against services you manage yourself:

```bash
uv run pytest                  # everything
uv run pytest -m "not integration"   # unit tests only, no services needed
```

Tests read the same environment variables as the app (`POSTGRES_*`, `REDIS_*`, `BASE_URL`, `RATE_LIMIT_PER_MINUTE`, …). **Point `POSTGRES_DB` at a throwaway database**: the `links` table is truncated before every integration test. In Redis only this app's keys (`link:*`, `clicks:*`, `ratelimit:*`) are deleted. If Postgres or Redis is unreachable, integration tests are skipped.

```bash
POSTGRES_DB=url_shortner_test uv run pytest
```

## Endpoints

| Method | Path | Description |
|---|---|---|
| POST | `/api/links` | `{url, custom_alias?, expires_in_days?}` → 201 link · 409 alias taken · 422 invalid · 429 rate limited |
| GET | `/api/links?limit=&offset=` | Newest links first, with `total` |
| GET | `/api/links/{code}` | One link with click stats |
| DELETE | `/api/links/{code}` | Delete link and evict its cache |
| GET/HEAD | `/{code}` | 307 redirect · 404 unknown · 410 expired |
| GET | `/api/health` | Postgres + Redis status |

## How Redis is used

- `link:{code}` — cached redirect target (TTL 1h, capped at the link's expiry), so hot redirects skip Postgres.
- `clicks:{code}` — real-time click counter; Postgres `links.clicks` is updated in a background task on each GET redirect (HEAD requests from link previews aren't counted).
- `ratelimit:{ip}:{minute}` — fixed-window limit on link creation (`RATE_LIMIT_PER_MINUTE`, default 20).

## Configuration (`.env`)

| Variable | Default |
|---|---|
| `POSTGRES_HOST` / `POSTGRES_PORT` | `localhost` / `5432` |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` | role used by the app |
| `POSTGRES_DB` | database name |
| `REDIS_HOST` / `REDIS_PORT` | `localhost` / `6379` |
| `BASE_URL` | `http://localhost:8001` (prefix for generated short links) |
| `CORS_ORIGINS` | `http://localhost:5173,http://localhost:5174` |
| `CACHE_TTL_SECONDS` | `3600` |
| `RATE_LIMIT_PER_MINUTE` | `20` |
