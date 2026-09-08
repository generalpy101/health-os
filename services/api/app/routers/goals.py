from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..deps import current_user
from ..models import User
from ..schemas import GoalIn, GoalOut, GoalPatch, TargetIn, TargetOut, TargetPatch
from ..services import goals as goals_service

router = APIRouter(tags=["goals"])


@router.get("/goals", response_model=list[GoalOut])
async def list_goals(status: str | None = None, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    return await goals_service.list_goals(db, user, status)


@router.post("/goals", response_model=GoalOut, status_code=201)
async def create_goal(data: GoalIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    return await goals_service.create_goal(db, user, data)


@router.patch("/goals/{goal_id}", response_model=GoalOut)
async def update_goal(goal_id: UUID, patch: GoalPatch, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    return await goals_service.update_goal(db, user, goal_id, patch)


@router.delete("/goals/{goal_id}", status_code=204)
async def delete_goal(goal_id: UUID, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    await goals_service.delete_goal(db, user, goal_id)
    return None


@router.get("/goals/{goal_id}/progress")
async def goal_progress(goal_id: UUID, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    return await goals_service.goal_progress(db, user, goal_id)


@router.get("/targets", response_model=list[TargetOut])
async def list_targets(all: bool = False, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    return await goals_service.list_targets(db, user, active_only=not all)


@router.post("/targets", response_model=TargetOut, status_code=201)
async def create_target(data: TargetIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    return await goals_service.create_target(db, user, data)


@router.patch("/targets/{target_id}", response_model=TargetOut)
async def update_target(target_id: UUID, patch: TargetPatch, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    return await goals_service.update_target(db, user, target_id, patch)


@router.delete("/targets/{target_id}", status_code=204)
async def deactivate_target(target_id: UUID, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    await goals_service.update_target(db, user, target_id, TargetPatch(active=False))
    return None
