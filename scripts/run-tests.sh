#!/usr/bin/env bash
# Run the test suite against throwaway Postgres + Redis containers.
#
#   ./scripts/run-tests.sh                 # all tests
#   ./scripts/run-tests.sh -k redirect -x  # extra args go to pytest
#   KEEP_CONTAINERS=1 ./scripts/run-tests.sh   # leave containers up afterwards
#
# Containers are torn down (with their data) on exit unless KEEP_CONTAINERS=1.
set -euo pipefail

cd "$(dirname "$0")/.."

# ---- Test configuration (overrides .env; pydantic-settings prefers real env vars) ----
export POSTGRES_HOST=127.0.0.1
export POSTGRES_PORT="${TEST_POSTGRES_PORT:-55432}"
export POSTGRES_USER=shorturl_test
export POSTGRES_PASSWORD=shorturl_test
export POSTGRES_DB=url_shortener_test

export REDIS_HOST=127.0.0.1
export REDIS_PORT="${TEST_REDIS_PORT:-56379}"

export BASE_URL=http://sho.rt
export CORS_ORIGINS=http://localhost:5173
export CACHE_TTL_SECONDS=3600
export RATE_LIMIT_PER_MINUTE=5

# Fail instead of skipping integration tests if the services can't be reached.
export REQUIRE_SERVICES=1

COMPOSE=(docker compose -p shorturl-test -f docker-compose.test.yml)

cleanup() {
  if [[ "${KEEP_CONTAINERS:-0}" == "1" ]]; then
    echo "==> Leaving test containers running (stop with: ${COMPOSE[*]} down -v)"
  else
    echo "==> Stopping test containers"
    "${COMPOSE[@]}" down -v --remove-orphans >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

if ! docker info >/dev/null 2>&1; then
  echo "Docker is not running. Start Docker Desktop and try again." >&2
  exit 1
fi

echo "==> Starting Postgres (:$POSTGRES_PORT) and Redis (:$REDIS_PORT)"
"${COMPOSE[@]}" up -d --wait --wait-timeout 60

echo "==> Running tests"
uv run pytest "$@"
