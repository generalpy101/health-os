from datetime import date, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Habit, HabitLog, User
from ..schemas import HabitIn, HabitLogIn
from ..utils.time import parse_date, user_today
from .common import audit, get_owned


async def create_habit(db: AsyncSession, user: User, data: HabitIn, source: str = "user") -> Habit:
    habit = Habit(user_id=user.id, **data.model_dump())
    db.add(habit)
    await audit(db, user.id, "habit_created", "habit", habit.id, {"name": habit.name, "source": source})
    await db.commit()
    await db.refresh(habit)
    return habit


async def list_habits(db: AsyncSession, user: User, active_only: bool = True) -> list[Habit]:
    stmt = select(Habit).where(Habit.user_id == user.id)
    if active_only:
        stmt = stmt.where(Habit.active.is_(True))
    result = await db.execute(stmt.order_by(Habit.created_at))
    return list(result.scalars().all())


async def update_habit(db: AsyncSession, user: User, habit_id: UUID, data: HabitIn) -> Habit:
    habit = await get_owned(db, Habit, habit_id, user)
    for key, value in data.model_dump(exclude_none=True).items():
        setattr(habit, key, value)
    await db.commit()
    await db.refresh(habit)
    return habit


async def delete_habit(db: AsyncSession, user: User, habit_id: UUID) -> None:
    habit = await get_owned(db, Habit, habit_id, user)
    habit.active = False
    await db.commit()


async def log_habit(db: AsyncSession, user: User, habit_id: UUID, data: HabitLogIn) -> HabitLog:
    habit = await get_owned(db, Habit, habit_id, user)
    day = parse_date(data.date, user.timezone)
    # upsert-ish: one log per habit/day
    result = await db.execute(
        select(HabitLog).where(HabitLog.habit_id == habit.id, HabitLog.date == day)
    )
    log = result.scalar_one_or_none()
    if log is None:
        log = HabitLog(user_id=user.id, habit_id=habit.id, date=day,
                       status=data.status, value=data.value, notes=data.notes)
        db.add(log)
    else:
        log.status = data.status
        log.value = data.value if data.value is not None else log.value
        log.notes = data.notes if data.notes is not None else log.notes
    await db.commit()
    await db.refresh(log)
    return log


async def habit_logs(db: AsyncSession, user: User, habit_id: UUID, days: int = 30) -> list[HabitLog]:
    start = user_today(user.timezone) - timedelta(days=days - 1)
    result = await db.execute(
        select(HabitLog).where(HabitLog.user_id == user.id, HabitLog.habit_id == habit_id, HabitLog.date >= start)
        .order_by(HabitLog.date)
    )
    return list(result.scalars().all())


async def habit_progress(db: AsyncSession, user: User, days: int = 7) -> list[dict]:
    habits = await list_habits(db, user)
    today = user_today(user.timezone)
    start = today - timedelta(days=days - 1)
    out = []
    for habit in habits:
        result = await db.execute(
            select(HabitLog).where(HabitLog.habit_id == habit.id, HabitLog.date >= start)
        )
        logs = result.scalars().all()
        completed = sum(1 for l in logs if l.status == "completed")
        by_date = {l.date: l for l in logs}
        # current streak
        streak = 0
        d = today
        while by_date.get(d) and by_date[d].status == "completed":
            streak += 1
            d -= timedelta(days=1)
        out.append({
            "habit_id": str(habit.id), "name": habit.name, "completed": completed,
            "window_days": days, "adherence": round(completed / days, 3), "streak": streak,
            "today_status": by_date[today].status if today in by_date else None,
            "today_log_id": str(by_date[today].id) if today in by_date else None,
        })
    return out
