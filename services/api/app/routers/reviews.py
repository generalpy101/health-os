"""AI reviews: cached weekly/monthly summaries with a provider-written narrative.

GET returns the cached review (generating inline on first read). A weekly review
older than 20h lazily enqueues a background refresh and serves the cached copy
meanwhile. Regenerate always enqueues a fresh generation and returns the cached
copy; the frontend refetches a few seconds later to pick it up.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..deps import current_user
from ..models import User
from ..services import reviews as reviews_service

router = APIRouter(prefix="/reviews", tags=["reviews"])


@router.get("/weekly")
async def weekly(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    review, _refreshing = await reviews_service.get_review(db, user, "weekly")
    return reviews_service.to_out(review)


@router.post("/weekly/regenerate")
async def weekly_regenerate(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    review, _queued = await reviews_service.regenerate_review(db, user, "weekly")
    return reviews_service.to_out(review)


@router.get("/monthly")
async def monthly(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    review, _refreshing = await reviews_service.get_review(db, user, "monthly")
    return reviews_service.to_out(review)


@router.post("/monthly/regenerate")
async def monthly_regenerate(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    review, _queued = await reviews_service.regenerate_review(db, user, "monthly")
    return reviews_service.to_out(review)
