from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app import models  # noqa: F401  (registers tables on Base.metadata)
from app.config import get_settings
from app.db import Base, engine, get_session
from app.redis_client import get_redis, redis
from app.routers import links, redirect


@asynccontextmanager
async def lifespan(_: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await redis.ping()
    yield
    await redis.aclose()
    await engine.dispose()


app = FastAPI(title="URL Shortener", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origin_list,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health", tags=["health"])
async def health(
    session: AsyncSession = Depends(get_session), r: Redis = Depends(get_redis)
) -> dict:
    status = {"postgres": "ok", "redis": "ok"}
    try:
        await session.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        status["postgres"] = f"error: {exc}"
    try:
        await r.ping()
    except Exception as exc:  # noqa: BLE001
        status["redis"] = f"error: {exc}"
    return status


app.include_router(links.router)
# Catch-all /{code} must be registered last so it never shadows /api or /docs.
app.include_router(redirect.router)
