from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..deps import current_user
from ..models import User
from ..schemas import (HabitIn, HabitLogIn, HabitLogOut, HabitOut, MeasurementIn, MeasurementOut,
                       SleepIn, SleepOut, WaterIn, WaterOut)
from ..services import habits as habits_service
from ..services import health as health_service
from ..utils.time import date_range, parse_date, user_today

router = APIRouter(tags=["health"])


@router.post("/water", response_model=WaterOut, status_code=201)
async def log_water(data: WaterIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    return await health_service.log_water(db, user, data)


@router.get("/water")
async def get_water(day: str | None = None, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    d = parse_date(day, user.timezone)
    logs = await health_service.list_water(db, user, d)
    total = await health_service.water_total(db, user, d)
    return {"date": d, "total_ml": total, "logs": logs}


@router.delete("/water/{log_id}", status_code=204)
async def delete_water(log_id: UUID, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    await health_service.delete_water(db, user, log_id)
    return None


@router.post("/sleep", response_model=SleepOut, status_code=201)
async def log_sleep(data: SleepIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    return await health_service.log_sleep(db, user, data)


@router.get("/sleep", response_model=list[SleepOut])
async def list_sleep(days: int = Query(default=30, le=365), user: User = Depends(current_user),
                     db: AsyncSession = Depends(get_db)):
    start, end = date_range(days, user.timezone)
    return await health_service.list_sleep(db, user, start, end)


@router.delete("/sleep/{log_id}", status_code=204)
async def delete_sleep(log_id: UUID, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    await health_service.delete_sleep(db, user, log_id)
    return None


@router.post("/measurements", response_model=MeasurementOut, status_code=201)
async def record_measurement(data: MeasurementIn, user: User = Depends(current_user),
                             db: AsyncSession = Depends(get_db)):
    return await health_service.record_measurement(db, user, data)


@router.get("/measurements", response_model=list[MeasurementOut])
async def list_measurements(type: str | None = None, days: int = Query(default=90, le=730),
                            user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    start, end = date_range(days, user.timezone)
    return await health_service.list_measurements(db, user, type, start, end)


@router.delete("/measurements/{m_id}", status_code=204)
async def delete_measurement(m_id: UUID, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    await health_service.delete_measurement(db, user, m_id)
    return None


@router.get("/measurements/trend/weight")
async def weight_trend(days: int = Query(default=30, le=730), user: User = Depends(current_user),
                       db: AsyncSession = Depends(get_db)):
    start, end = date_range(days, user.timezone)
    return await health_service.weight_trend(db, user, start, end)


# ---------- habits ----------

@router.get("/habits", response_model=list[HabitOut])
async def list_habits(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    return await habits_service.list_habits(db, user)


@router.post("/habits", response_model=HabitOut, status_code=201)
async def create_habit(data: HabitIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    return await habits_service.create_habit(db, user, data)


@router.put("/habits/{habit_id}", response_model=HabitOut)
async def update_habit(habit_id: UUID, data: HabitIn, user: User = Depends(current_user),
                       db: AsyncSession = Depends(get_db)):
    return await habits_service.update_habit(db, user, habit_id, data)


@router.delete("/habits/{habit_id}", status_code=204)
async def delete_habit(habit_id: UUID, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    await habits_service.delete_habit(db, user, habit_id)
    return None


@router.post("/habits/{habit_id}/logs", response_model=HabitLogOut, status_code=201)
async def log_habit(habit_id: UUID, data: HabitLogIn, user: User = Depends(current_user),
                    db: AsyncSession = Depends(get_db)):
    return await habits_service.log_habit(db, user, habit_id, data)


@router.get("/habits/{habit_id}/logs", response_model=list[HabitLogOut])
async def get_habit_logs(habit_id: UUID, days: int = Query(default=30, le=365),
                         user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    return await habits_service.habit_logs(db, user, habit_id, days)


@router.get("/habits-progress")
async def habit_progress(days: int = Query(default=7, le=90), user: User = Depends(current_user),
                         db: AsyncSession = Depends(get_db)):
    return await habits_service.habit_progress(db, user, days)
