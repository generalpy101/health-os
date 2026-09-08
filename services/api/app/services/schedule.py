from datetime import date, datetime, time, timedelta, timezone
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import ScheduleEvent, User
from ..schemas import EventIn, EventPatch
from .common import audit, get_owned


def _to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


async def create_event(db: AsyncSession, user: User, data: EventIn, source: str = "user") -> ScheduleEvent:
    start = _to_utc(data.start_at)
    end = _to_utc(data.end_at) if data.end_at else None
    if end and end <= start:
        from fastapi import HTTPException
        raise HTTPException(422, "end_at must be after start_at")
    event = ScheduleEvent(
        user_id=user.id, type=data.type, title=data.title, start_at=start, end_at=end,
        timezone=user.timezone, recurrence=data.recurrence, source=source,
        linked_entity_type=data.linked_entity_type, linked_entity_id=data.linked_entity_id, meta=data.meta,
    )
    db.add(event)
    await audit(db, user.id, "schedule_changed", "schedule_event", event.id,
                {"action": "created", "title": event.title, "source": source})
    await db.commit()
    await db.refresh(event)
    return event


def _occurrences(event: ScheduleEvent, range_start: datetime, range_end: datetime) -> list[datetime]:
    """Expand an event into occurrence start times within [range_start, range_end]."""
    start = event.start_at if event.start_at.tzinfo else event.start_at.replace(tzinfo=timezone.utc)
    rec = event.recurrence or {}
    freq = rec.get("freq")
    if not freq:
        return [start] if range_start <= start <= range_end else []
    out: list[datetime] = []
    duration_days = 1 if freq == "daily" else 7
    bydays: list[int] | None = rec.get("bydays")  # weekday numbers, Monday=0
    cursor = range_start
    while cursor <= range_end:
        candidate = datetime.combine(cursor.date(), start.timetz())
        if candidate >= start and range_start <= candidate <= range_end:
            if freq == "daily":
                out.append(candidate)
            elif freq == "weekly":
                if bydays is None and candidate.weekday() == start.weekday():
                    out.append(candidate)
                elif bydays is not None and candidate.weekday() in bydays:
                    out.append(candidate)
        cursor += timedelta(days=duration_days if freq == "daily" else 1)
    return out


async def get_schedule(db: AsyncSession, user: User, start: date, end: date) -> list[dict]:
    range_start = datetime.combine(start, time.min, tzinfo=ZoneInfo(user.timezone))
    range_end = datetime.combine(end, time.max, tzinfo=ZoneInfo(user.timezone))
    result = await db.execute(
        select(ScheduleEvent).where(
            ScheduleEvent.user_id == user.id,
            ScheduleEvent.status != "cancelled",
            ScheduleEvent.start_at <= range_end,
        )
    )
    events = []
    for e in result.scalars().all():
        duration = (e.end_at - e.start_at) if e.end_at else None
        for occ in _occurrences(e, range_start, range_end):
            events.append({
                "id": str(e.id), "type": e.type, "title": e.title,
                "start_at": occ, "end_at": (occ + duration) if duration else None,
                "recurring": bool(e.recurrence), "status": e.status, "source": e.source,
                "meta": e.meta or {},
            })
    events.sort(key=lambda x: x["start_at"])
    return events


async def update_event(db: AsyncSession, user: User, event_id: UUID, patch: EventPatch,
                       source: str = "user") -> ScheduleEvent:
    event = await get_owned(db, ScheduleEvent, event_id, user)
    changes = patch.model_dump(exclude_none=True)
    if "start_at" in changes:
        changes["start_at"] = _to_utc(changes["start_at"])
    if "end_at" in changes and changes["end_at"]:
        changes["end_at"] = _to_utc(changes["end_at"])
    new_start = changes.get("start_at", event.start_at)
    new_end = changes.get("end_at", event.end_at)
    if new_end and new_start and _to_utc(new_end) <= _to_utc(new_start):
        from fastapi import HTTPException
        raise HTTPException(422, "end_at must be after start_at")
    for key, value in changes.items():
        setattr(event, key, value)
    await audit(db, user.id, "schedule_changed", "schedule_event", event.id,
                {"action": "updated", "changes": {k: str(v) for k, v in changes.items()}, "source": source})
    await db.commit()
    await db.refresh(event)
    return event


async def delete_event(db: AsyncSession, user: User, event_id: UUID) -> None:
    event = await get_owned(db, ScheduleEvent, event_id, user)
    await db.delete(event)
    await audit(db, user.id, "schedule_changed", "schedule_event", event_id, {"action": "deleted"})
    await db.commit()


async def find_free_slots(db: AsyncSession, user: User, day: date, duration_min: int = 60,
                          day_start: int = 6, day_end: int = 23) -> list[dict]:
    """Deterministic free-slot finder for a given local day."""
    tz = ZoneInfo(user.timezone)
    events = await get_schedule(db, user, day, day)
    busy = []
    for e in events:
        s = e["start_at"].astimezone(tz)
        en = (e["end_at"] or e["start_at"]).astimezone(tz)
        busy.append((s, en))
    busy.sort()
    free = []
    cursor = datetime.combine(day, time(day_start, 0), tzinfo=tz)
    end_of_day = datetime.combine(day, time(day_end, 0), tzinfo=tz)
    for s, en in busy:
        if (s - cursor).total_seconds() >= duration_min * 60:
            free.append({"start_at": cursor, "end_at": s})
        cursor = max(cursor, en)
    if (end_of_day - cursor).total_seconds() >= duration_min * 60:
        free.append({"start_at": cursor, "end_at": end_of_day})
    return free
