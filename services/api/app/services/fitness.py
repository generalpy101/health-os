from datetime import date
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Activity, Exercise, User, WorkoutPlan, WorkoutSession
from ..schemas import ActivityIn, WorkoutIn, WorkoutPlanIn
from ..utils import metrics
from ..utils.time import parse_date
from . import prs as prs_service
from .common import audit, get_owned
from .versions import record_version, row_snapshot


async def search_exercises(db: AsyncSession, query: str = "", limit: int = 25) -> list[Exercise]:
    stmt = select(Exercise)
    if query:
        stmt = stmt.where(or_(Exercise.name.ilike(f"%{query}%")))
    result = await db.execute(stmt.order_by(Exercise.name).limit(min(limit, 100)))
    return list(result.scalars().all())


async def log_workout(db: AsyncSession, user: User, data: WorkoutIn, source: str = "manual") -> WorkoutSession:
    exercises = [e.model_dump(exclude_none=True) for e in data.exercises]
    # TRACK D: PRs are computed against all prior sessions BEFORE inserting this one
    prior = await db.execute(select(WorkoutSession).where(WorkoutSession.user_id == user.id))
    new_prs = prs_service.detect_new_prs(list(prior.scalars().all()), exercises)
    session = WorkoutSession(
        user_id=user.id,
        date=parse_date(data.date, user.timezone),
        title=data.title,
        duration_min=data.duration_min,
        exercises=exercises,
        total_volume=metrics.workout_volume(exercises),
        notes=data.notes,
        source=source,
    )
    db.add(session)
    await audit(db, user.id, "workout_logged", "workout_session", session.id,
                {"title": session.title, "volume": session.total_volume})
    if new_prs:
        await audit(db, user.id, "workout_pr", "workout_session", session.id, {"prs": new_prs})
    await db.commit()
    await db.refresh(session)
    session.new_prs = new_prs  # transient; surfaced via WorkoutOut.new_prs
    return session


async def list_workouts(db: AsyncSession, user: User, start: date | None = None, end: date | None = None,
                        limit: int = 50, offset: int = 0) -> list[WorkoutSession]:
    stmt = select(WorkoutSession).where(WorkoutSession.user_id == user.id)
    if start:
        stmt = stmt.where(WorkoutSession.date >= start)
    if end:
        stmt = stmt.where(WorkoutSession.date <= end)
    result = await db.execute(
        stmt.order_by(WorkoutSession.date.desc()).limit(min(limit, 200)).offset(offset)
    )
    return list(result.scalars().all())


async def update_workout(db: AsyncSession, user: User, session_id: UUID, data: WorkoutIn) -> WorkoutSession:
    session = await get_owned(db, WorkoutSession, session_id, user)
    exercises = [e.model_dump(exclude_none=True) for e in data.exercises]
    session.title = data.title
    session.duration_min = data.duration_min
    session.exercises = exercises
    session.total_volume = metrics.workout_volume(exercises)
    if data.date is not None:
        session.date = parse_date(data.date, user.timezone)
    if data.notes is not None:
        session.notes = data.notes
    await audit(db, user.id, "workout_updated", "workout_session", session.id, {"title": session.title})
    await db.commit()
    await db.refresh(session)
    return session


async def delete_workout(db: AsyncSession, user: User, session_id: UUID) -> None:
    session = await get_owned(db, WorkoutSession, session_id, user)
    await db.delete(session)
    await db.commit()


async def weekly_volume(db: AsyncSession, user: User, start: date, end: date) -> float:
    result = await db.execute(
        select(func.coalesce(func.sum(WorkoutSession.total_volume), 0)).where(
            WorkoutSession.user_id == user.id, WorkoutSession.date >= start, WorkoutSession.date <= end
        )
    )
    return round(result.scalar_one(), 1)


# ---------- plans ----------

async def create_plan(db: AsyncSession, user: User, data: WorkoutPlanIn, source: str = "user") -> WorkoutPlan:
    plan = WorkoutPlan(user_id=user.id, **data.model_dump())
    db.add(plan)
    await audit(db, user.id, "workout_plan_created", "workout_plan", plan.id, {"name": plan.name})
    await db.commit()
    await db.refresh(plan)
    return plan


async def list_plans(db: AsyncSession, user: User) -> list[WorkoutPlan]:
    result = await db.execute(
        select(WorkoutPlan).where(WorkoutPlan.user_id == user.id).order_by(WorkoutPlan.created_at.desc())
    )
    return list(result.scalars().all())


async def update_plan(db: AsyncSession, user: User, plan_id: UUID, data: WorkoutPlanIn,
                      *, reason: str | None = None, actor: str = "user") -> WorkoutPlan:
    plan = await get_owned(db, WorkoutPlan, plan_id, user)
    await record_version(db, user.id, "workout_plan", plan.id, row_snapshot(plan),
                         reason or "plan update", actor)
    for key, value in data.model_dump().items():
        setattr(plan, key, value)
    await db.commit()
    await db.refresh(plan)
    return plan


async def delete_plan(db: AsyncSession, user: User, plan_id: UUID) -> None:
    plan = await get_owned(db, WorkoutPlan, plan_id, user)
    await db.delete(plan)
    await db.commit()


# ---------- activities ----------

async def log_activity(db: AsyncSession, user: User, data: ActivityIn, source: str = "manual") -> Activity:
    activity = Activity(user_id=user.id, date=parse_date(data.date, user.timezone), source=source,
                        **data.model_dump(exclude={"date"}))
    db.add(activity)
    await audit(db, user.id, "activity_logged", "activity", activity.id, {"type": activity.type})
    await db.commit()
    await db.refresh(activity)
    return activity


async def list_activities(db: AsyncSession, user: User, start: date | None = None, end: date | None = None,
                          limit: int = 50) -> list[Activity]:
    stmt = select(Activity).where(Activity.user_id == user.id)
    if start:
        stmt = stmt.where(Activity.date >= start)
    if end:
        stmt = stmt.where(Activity.date <= end)
    result = await db.execute(stmt.order_by(Activity.date.desc()).limit(min(limit, 200)))
    return list(result.scalars().all())


async def update_activity(db: AsyncSession, user: User, activity_id: UUID, data: ActivityIn) -> Activity:
    activity = await get_owned(db, Activity, activity_id, user)
    for key, value in data.model_dump(exclude={"date"}, exclude_none=True).items():
        setattr(activity, key, value)
    if data.date is not None:
        activity.date = parse_date(data.date, user.timezone)
    await db.commit()
    await db.refresh(activity)
    return activity


async def delete_activity(db: AsyncSession, user: User, activity_id: UUID) -> None:
    activity = await get_owned(db, Activity, activity_id, user)
    await db.delete(activity)
    await db.commit()
