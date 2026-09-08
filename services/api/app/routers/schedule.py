from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..deps import current_user
from ..models import User
from ..schemas import EventIn, EventOut, EventPatch
from ..services import schedule as schedule_service

router = APIRouter(tags=["schedule"])


@router.get("/schedule")
async def get_schedule(start: date, end: date | None = None, user: User = Depends(current_user),
                       db: AsyncSession = Depends(get_db)):
    return await schedule_service.get_schedule(db, user, start, end or start)


@router.post("/schedule/events", response_model=EventOut, status_code=201)
async def create_event(data: EventIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    return await schedule_service.create_event(db, user, data)


@router.patch("/schedule/events/{event_id}", response_model=EventOut)
async def update_event(event_id: UUID, patch: EventPatch, user: User = Depends(current_user),
                       db: AsyncSession = Depends(get_db)):
    return await schedule_service.update_event(db, user, event_id, patch)


@router.delete("/schedule/events/{event_id}", status_code=204)
async def delete_event(event_id: UUID, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    await schedule_service.delete_event(db, user, event_id)
    return None


@router.get("/schedule/free-slots")
async def free_slots(day: date, duration_min: int = 60, user: User = Depends(current_user),
                     db: AsyncSession = Depends(get_db)):
    return await schedule_service.find_free_slots(db, user, day, duration_min)
