from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import Link
from app.redis_client import get_redis
from app.schemas import LinkCreate, LinkList, LinkOut
from app.services import cache
from app.services.shortcode import RESERVED, generate_code

router = APIRouter(prefix="/api/links", tags=["links"])

MAX_CODE_ATTEMPTS = 5


@router.post("", response_model=LinkOut, status_code=status.HTTP_201_CREATED)
async def create_link(
    payload: LinkCreate,
    request: Request,
    session: AsyncSession = Depends(get_session),
    r: Redis = Depends(get_redis),
) -> Link:
    client_id = request.client.host if request.client else "unknown"
    if await cache.hit_rate_limit(r, client_id):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many links created, slow down a bit.")

    expires_at = (
        datetime.now(timezone.utc) + timedelta(days=payload.expires_in_days)
        if payload.expires_in_days
        else None
    )

    if payload.custom_alias and payload.custom_alias.lower() in RESERVED:
        raise HTTPException(status.HTTP_409_CONFLICT, "That alias is reserved.")

    attempts = 1 if payload.custom_alias else MAX_CODE_ATTEMPTS
    for _ in range(attempts):
        link = Link(
            code=payload.custom_alias or generate_code(),
            target_url=str(payload.url),
            expires_at=expires_at,
        )
        session.add(link)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            continue
        await session.refresh(link)
        await cache.cache_link(r, link.code, link.target_url, link.expires_at)
        return link

    if payload.custom_alias:
        raise HTTPException(status.HTTP_409_CONFLICT, "That alias is already taken.")
    raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Could not generate a unique code.")


@router.get("", response_model=LinkList)
async def list_links(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> dict:
    total = await session.scalar(select(func.count()).select_from(Link))
    rows = await session.scalars(
        select(Link).order_by(Link.created_at.desc(), Link.id.desc()).limit(limit).offset(offset)
    )
    return {"items": list(rows), "total": total or 0}


@router.get("/{code}", response_model=LinkOut)
async def get_link(code: str, session: AsyncSession = Depends(get_session)) -> Link:
    link = await session.scalar(select(Link).where(Link.code == code))
    if link is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Link not found.")
    return link


@router.delete("/{code}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_link(
    code: str,
    session: AsyncSession = Depends(get_session),
    r: Redis = Depends(get_redis),
) -> Response:
    link = await session.scalar(select(Link).where(Link.code == code))
    if link is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Link not found.")
    await session.delete(link)
    await session.commit()
    await cache.evict_link(r, code)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
