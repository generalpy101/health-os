from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..deps import current_user
from ..models import User
from ..schemas import (ActivityIn, ActivityOut, ExerciseOut, WorkoutIn, WorkoutOut,
                       WorkoutPlanIn, WorkoutPlanOut)
from ..services import fitness as fitness_service

router = APIRouter(tags=["fitness"])


@router.get("/exercises", response_model=list[ExerciseOut])
async def search_exercises(q: str = "", limit: int = Query(default=25, le=100),
                           db: AsyncSession = Depends(get_db), user: User = Depends(current_user)):
    return await fitness_service.search_exercises(db, q, limit)


@router.post("/workout-sessions", response_model=WorkoutOut, status_code=201)
async def log_workout(data: WorkoutIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    return await fitness_service.log_workout(db, user, data)


@router.get("/workout-sessions", response_model=list[WorkoutOut])
async def list_workouts(start: date | None = None, end: date | None = None, limit: int = 50, offset: int = 0,
                        user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    return await fitness_service.list_workouts(db, user, start, end, limit, offset)


@router.patch("/workout-sessions/{session_id}", response_model=WorkoutOut)
async def update_workout(session_id: UUID, data: WorkoutIn, user: User = Depends(current_user),
                         db: AsyncSession = Depends(get_db)):
    return await fitness_service.update_workout(db, user, session_id, data)


@router.delete("/workout-sessions/{session_id}", status_code=204)
async def delete_workout(session_id: UUID, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    await fitness_service.delete_workout(db, user, session_id)
    return None


@router.get("/workout-plans", response_model=list[WorkoutPlanOut])
async def list_plans(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    return await fitness_service.list_plans(db, user)


@router.post("/workout-plans", response_model=WorkoutPlanOut, status_code=201)
async def create_plan(data: WorkoutPlanIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    return await fitness_service.create_plan(db, user, data)


@router.put("/workout-plans/{plan_id}", response_model=WorkoutPlanOut)
async def update_plan(plan_id: UUID, data: WorkoutPlanIn, user: User = Depends(current_user),
                      db: AsyncSession = Depends(get_db)):
    return await fitness_service.update_plan(db, user, plan_id, data)


@router.delete("/workout-plans/{plan_id}", status_code=204)
async def delete_plan(plan_id: UUID, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    await fitness_service.delete_plan(db, user, plan_id)
    return None


@router.post("/activities", response_model=ActivityOut, status_code=201)
async def log_activity(data: ActivityIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    return await fitness_service.log_activity(db, user, data)


@router.get("/activities", response_model=list[ActivityOut])
async def list_activities(start: date | None = None, end: date | None = None, limit: int = 50,
                          user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    return await fitness_service.list_activities(db, user, start, end, limit)


@router.patch("/activities/{activity_id}", response_model=ActivityOut)
async def update_activity(activity_id: UUID, data: ActivityIn, user: User = Depends(current_user),
                          db: AsyncSession = Depends(get_db)):
    return await fitness_service.update_activity(db, user, activity_id, data)


@router.delete("/activities/{activity_id}", status_code=204)
async def delete_activity(activity_id: UUID, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    await fitness_service.delete_activity(db, user, activity_id)
    return None
