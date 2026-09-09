from datetime import date, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Goal, Measurement, Target, User
from ..schemas import GoalIn, GoalPatch, TargetIn, TargetPatch
from ..utils import metrics
from .common import audit, get_owned
from .versions import record_version, row_snapshot


async def create_goal(db: AsyncSession, user: User, data: GoalIn, source: str = "user") -> Goal:
    goal = Goal(user_id=user.id, **data.model_dump())
    db.add(goal)
    await audit(db, user.id, "goal_created", "goal", goal.id, {"source": source, "title": goal.title})
    await db.commit()
    await db.refresh(goal)
    return goal


async def list_goals(db: AsyncSession, user: User, status_filter: str | None = None) -> list[Goal]:
    stmt = select(Goal).where(Goal.user_id == user.id).order_by(Goal.created_at.desc())
    if status_filter:
        stmt = stmt.where(Goal.status == status_filter)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def update_goal(db: AsyncSession, user: User, goal_id: UUID, patch: GoalPatch,
                      *, reason: str | None = None, actor: str = "user") -> Goal:
    goal = await get_owned(db, Goal, goal_id, user)
    changes = patch.model_dump(exclude_none=True)
    await record_version(db, user.id, "goal", goal.id, row_snapshot(goal),
                         reason or "goal update", actor)
    for key, value in changes.items():
        setattr(goal, key, value)
    await audit(db, user.id, "goal_changed", "goal", goal.id, changes)
    await db.commit()
    await db.refresh(goal)
    return goal


async def delete_goal(db: AsyncSession, user: User, goal_id: UUID) -> None:
    goal = await get_owned(db, Goal, goal_id, user)
    goal.status = "archived"  # soft archive; never silently destroy history
    await audit(db, user.id, "goal_archived", "goal", goal.id)
    await db.commit()


async def goal_progress(db: AsyncSession, user: User, goal_id: UUID) -> dict:
    from ..utils.time import user_today

    goal = await get_owned(db, Goal, goal_id, user)
    out: dict = {"goal_id": str(goal.id), "progress": None, "current": None}
    if goal.type in ("weight_loss", "weight_gain") and goal.unit in ("kg", "lb", None):
        latest = await current_weight(db, user)
        if latest is not None:
            out["current"] = latest
            out["progress"] = metrics.goal_progress(goal.type, goal.start_value, goal.target_value, latest)

        # deadline forecast: required pace vs actual pace, projection at the date
        if goal.target_date and latest is not None:
            today = user_today(user.timezone)
            days_left = (goal.target_date - today).days
            if days_left > 0 and goal.start_value is not None and goal.target_value is not None:
                remaining_per_day = (goal.target_value - latest) / days_left
                start = today - timedelta(days=30)
                trend = await _weight_slope(db, user, start, today)
                out["forecast"] = {
                    "target_date": goal.target_date.isoformat(),
                    "days_left": days_left,
                    "needed_per_week": round(remaining_per_day * 7, 2),
                    "actual_per_week": round(trend * 7, 2) if trend is not None else None,
                    "projected_at_date": round(latest + trend * days_left, 1) if trend is not None else None,
                    "on_track": (
                        (trend is not None)
                        and (trend * (goal.target_value - goal.start_value) >= remaining_per_day * (goal.target_value - goal.start_value))
                    ),
                }
    return out


async def _weight_slope(db: AsyncSession, user: User, start: date, end: date) -> float | None:
    from . import health as health_service

    trend = await health_service.weight_trend(db, user, start, end)
    return trend["slope_per_day"]


# ---------- targets ----------

async def create_target(db: AsyncSession, user: User, data: TargetIn, *, actor: str | None = None) -> Target:
    # replace an active target of the same key+period (keep history by deactivating)
    result = await db.execute(
        select(Target).where(Target.user_id == user.id, Target.key == data.key,
                             Target.period == data.period, Target.active.is_(True))
    )
    if actor is None:
        actor = "ai" if data.source == "ai" else "user"
    for old in result.scalars().all():
        await record_version(db, user.id, "target", old.id, row_snapshot(old),
                             f"replaced by new {data.key} target", actor)
        old.active = False
    target = Target(user_id=user.id, effective_from=date.today(), **data.model_dump())
    db.add(target)
    await audit(db, user.id, "target_changed", "target", target.id, data.model_dump(mode="json"))
    await db.commit()
    await db.refresh(target)
    return target


async def list_targets(db: AsyncSession, user: User, active_only: bool = True) -> list[Target]:
    stmt = select(Target).where(Target.user_id == user.id)
    if active_only:
        stmt = stmt.where(Target.active.is_(True))
    result = await db.execute(stmt.order_by(Target.key))
    return list(result.scalars().all())


async def update_target(db: AsyncSession, user: User, target_id: UUID, patch: TargetPatch,
                        *, reason: str | None = None, actor: str = "user") -> Target:
    target = await get_owned(db, Target, target_id, user)
    changes = patch.model_dump(exclude_none=True)
    await record_version(db, user.id, "target", target.id, row_snapshot(target),
                         reason or "target update", actor)
    for key, value in changes.items():
        setattr(target, key, value)
    if target.active:
        # one active target per key+period — reactivating this one retires the rest
        # (versioned, so the superseded target's state stays revertible)
        siblings = await db.execute(
            select(Target).where(Target.user_id == user.id, Target.key == target.key,
                                 Target.period == target.period, Target.active.is_(True),
                                 Target.id != target.id)
        )
        for sib in siblings.scalars().all():
            await record_version(db, user.id, "target", sib.id, row_snapshot(sib),
                                 f"superseded by {target.key} target update", actor)
            sib.active = False
    await audit(db, user.id, "target_changed", "target", target.id, changes)
    await db.commit()
    await db.refresh(target)
    return target


async def targets_map(db: AsyncSession, user: User) -> dict[str, float]:
    targets = await list_targets(db, user)
    return {t.key: t.value for t in targets if t.period == "daily"}


async def current_weight(db: AsyncSession, user: User) -> float | None:
    result = await db.execute(
        select(func.max(Measurement.date)).where(Measurement.user_id == user.id, Measurement.type == "weight")
    )
    latest_date = result.scalar_one_or_none()
    if latest_date is None:
        return None
    result = await db.execute(
        select(Measurement.value).where(
            Measurement.user_id == user.id, Measurement.type == "weight", Measurement.date == latest_date
        ).order_by(Measurement.created_at.desc()).limit(1)
    )
    return result.scalar_one_or_none()
