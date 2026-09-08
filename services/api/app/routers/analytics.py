from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..deps import current_user
from ..models import User
from ..services import analytics as analytics_service

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/daily")
async def daily(day: date | None = None, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    return await analytics_service.daily_summary(db, user, day)


@router.get("/weekly")
async def weekly(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    return await analytics_service.weekly_summary(db, user)


@router.get("/monthly")
async def monthly(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    return await analytics_service.monthly_summary(db, user)


@router.get("/range")
async def range_(days: int = Query(default=30, le=730), user: User = Depends(current_user),
                 db: AsyncSession = Depends(get_db)):
    return await analytics_service.range_summary(db, user, days)
