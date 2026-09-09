from datetime import date
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..deps import current_user
from ..models import User
from ..schemas import FoodIn, FoodLogIn, FoodLogOut, FoodLogPatch, FoodOut, NutritionDayOut
from ..services import goals as goals_service
from ..services import nutrition as nutrition_service
from ..utils.time import parse_date

router = APIRouter(tags=["nutrition"])


@router.get("/foods/search", response_model=list[FoodOut])
async def search_foods(q: str = "", limit: int = Query(default=20, le=100),
                       provider: Literal["local", "remote", "auto"] = "auto",  # TRACK A
                       user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    return await nutrition_service.search_foods_with_providers(db, user, q, limit, provider)


# TRACK A
@router.get("/foods/barcode/{code}", response_model=FoodOut)
async def food_by_barcode(code: str, user: User = Depends(current_user),
                          db: AsyncSession = Depends(get_db)):
    food = await nutrition_service.food_by_barcode(db, user, code)
    if food is None:
        raise HTTPException(404, detail="not found")
    return food


@router.post("/foods", response_model=FoodOut, status_code=201)
async def create_food(data: FoodIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    return await nutrition_service.create_food(db, user, data)


@router.post("/food-logs", response_model=FoodLogOut, status_code=201)
async def log_food(data: FoodLogIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    return await nutrition_service.log_food(db, user, data)


@router.get("/food-logs", response_model=list[FoodLogOut])
async def list_food_logs(day: date | None = None, start: date | None = None, end: date | None = None,
                         limit: int = 50, offset: int = 0, calendar: bool = False,
                         user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    return await nutrition_service.list_food_logs(db, user, day, start, end, limit, offset, calendar)


@router.patch("/food-logs/{log_id}", response_model=FoodLogOut)
async def patch_food_log(log_id: UUID, data: FoodLogPatch, user: User = Depends(current_user),
                         db: AsyncSession = Depends(get_db)):
    return await nutrition_service.update_food_log(
        db, user, log_id, meal_type=data.meal_type, note=data.note, time=data.time,
        items=data.items)


@router.delete("/food-logs/{log_id}", status_code=204)
async def delete_food_log(log_id: UUID, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    await nutrition_service.delete_food_log(db, user, log_id)
    return None


@router.get("/nutrition/daily", response_model=NutritionDayOut)
async def daily_nutrition(day: str | None = None, user: User = Depends(current_user),
                          db: AsyncSession = Depends(get_db)):
    # no day passed → the user's current logical day (boundary-aware)
    if day is None:
        from ..services.common import day_start_minutes
        from ..utils.time import logical_today
        d = logical_today(user.timezone, await day_start_minutes(db, user))
    else:
        d = parse_date(day, user.timezone)
    totals = await nutrition_service.daily_totals(db, user, d)
    logs = await nutrition_service.list_food_logs(db, user, day=d)
    targets = await goals_service.targets_map(db, user)
    return {**totals, "logs": logs,
            "targets": {k: targets[k] for k in ("calories", "protein") if k in targets}}


@router.get("/nutrition/history")
async def nutrition_history(days: int = Query(default=30, le=365), user: User = Depends(current_user),
                            db: AsyncSession = Depends(get_db)):
    from ..utils.time import date_range
    start, end = date_range(days, user.timezone)
    return await nutrition_service.nutrition_history(db, user, start, end)
