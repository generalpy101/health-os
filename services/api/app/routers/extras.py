"""Track D — daily-use depth: saved meals, frequent foods, PRs, calendar, insights."""

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..deps import current_user
from ..models import User
from ..schemas import (ActivityDayOut, FoodLogOut, FrequentFoodOut, PROut, SavedMealIn,
                       SavedMealLogIn, SavedMealOut, StallOut)
from ..services import analytics as analytics_service
from ..services import insights as insights_service
from ..services import prs as prs_service
from ..services import saved_meals as saved_meals_service

router = APIRouter(tags=["extras"])


# ---------- saved meals ----------

@router.get("/saved-meals", response_model=list[SavedMealOut])
async def list_saved_meals(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    return await saved_meals_service.list_saved_meals(db, user)


@router.post("/saved-meals", response_model=SavedMealOut, status_code=201)
async def create_saved_meal(data: SavedMealIn, user: User = Depends(current_user),
                            db: AsyncSession = Depends(get_db)):
    return await saved_meals_service.create_saved_meal(db, user, data)


@router.post("/saved-meals/{meal_id}/log", response_model=FoodLogOut, status_code=201)
async def log_saved_meal(meal_id: UUID, data: SavedMealLogIn, user: User = Depends(current_user),
                         db: AsyncSession = Depends(get_db)):
    return await saved_meals_service.log_saved_meal(db, user, meal_id, data)


@router.delete("/saved-meals/{meal_id}", status_code=204)
async def delete_saved_meal(meal_id: UUID, user: User = Depends(current_user),
                            db: AsyncSession = Depends(get_db)):
    await saved_meals_service.delete_saved_meal(db, user, meal_id)
    return None


# ---------- frequent foods ----------

@router.get("/foods/frequent", response_model=list[FrequentFoodOut])
async def frequent_foods(limit: int = Query(default=12, le=50), user: User = Depends(current_user),
                         db: AsyncSession = Depends(get_db)):
    return await saved_meals_service.frequent_foods(db, user, limit)


# ---------- PRs ----------

@router.get("/workouts/prs", response_model=list[PROut])
async def personal_records(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    return await prs_service.personal_records(db, user)


# ---------- activity calendar ----------

@router.get("/analytics/activity-calendar", response_model=list[ActivityDayOut])
async def activity_calendar(days: int = Query(default=180, le=400), user: User = Depends(current_user),
                            db: AsyncSession = Depends(get_db)):
    return await analytics_service.activity_calendar(db, user, days)


# ---------- insights ----------

@router.get("/insights/stall", response_model=StallOut)
async def stall_check(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    return await insights_service.stall_check(db, user)
