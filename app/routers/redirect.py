from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from redis.asyncio import Redis
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import SessionLocal, get_session
from app.models import Link
from app.redis_client import get_redis
from app.services import cache

router = APIRouter(tags=["redirect"])


async def record_click(code: str) -> None:
    async with SessionLocal() as session:
        await session.execute(
            update(Link)
            .where(Link.code == code)
            .values(clicks=Link.clicks + 1, last_clicked_at=datetime.now(timezone.utc))
        )
        await session.commit()


@router.api_route("/{code}", methods=["GET", "HEAD"], include_in_schema=False)
async def redirect(
    code: str,
    request: Request,
    background: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
    r: Redis = Depends(get_redis),
) -> RedirectResponse:
    cached = await cache.get_cached_link(r, code)
    if cached:
        target_url = cached["target_url"]
        expires_at = datetime.fromisoformat(cached["expires_at"]) if cached["expires_at"] else None
    else:
        link = await session.scalar(select(Link).where(Link.code == code))
        if link is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Link not found.")
        target_url, expires_at = link.target_url, link.expires_at
        await cache.cache_link(r, code, target_url, expires_at)

    if expires_at and expires_at <= datetime.now(timezone.utc):
        raise HTTPException(status.HTTP_410_GONE, "This link has expired.")

    # HEAD requests come from link previews and crawlers; only count real visits.
    if request.method == "GET":
        await cache.incr_clicks(r, code)
        background.add_task(record_click, code)
    return RedirectResponse(target_url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)
