from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import (Activity, FoodLog, Habit, HabitLog, Measurement, SleepLog, User, WaterLog,
                      WorkoutSession)
from ..utils import metrics
from ..utils.time import user_today, week_start
from . import goals as goals_service
from . import habits as habits_service
from . import health as health_service
from . import nutrition as nutrition_service
from . import schedule as schedule_service


async def daily_summary(db: AsyncSession, user: User, day: date | None = None) -> dict:
    day = day or user_today(user.timezone)
    nutrition = await nutrition_service.daily_totals(db, user, day)
    water = await health_service.water_total(db, user, day)
    sleep_q = await db.execute(
        select(SleepLog).where(SleepLog.user_id == user.id, SleepLog.date == day)
        .order_by(SleepLog.created_at.desc()).limit(1)
    )
    sleep = sleep_q.scalar_one_or_none()
    workouts_q = await db.execute(
        select(func.count(), func.coalesce(func.sum(WorkoutSession.total_volume), 0)).where(
            WorkoutSession.user_id == user.id, WorkoutSession.date == day
        )
    )
    workout_count, workout_volume = workouts_q.one()
    steps_q = await db.execute(
        select(func.coalesce(func.sum(Activity.steps), 0)).where(
            Activity.user_id == user.id, Activity.date == day
        )
    )
    steps = steps_q.scalar_one()
    habits = await habits_service.habit_progress(db, user, days=1)
    habits_done = sum(1 for h in habits if h["today_status"] == "completed")
    events = await schedule_service.get_schedule(db, user, day, day)
    targets = await goals_service.targets_map(db, user)
    weight = await goals_service.current_weight(db, user)

    return {
        "date": day,
        "nutrition": {k: nutrition[k] for k in ("calories", "protein", "carbs", "fat", "fiber")},
        "water_ml": water,
        "sleep_minutes": sleep.duration_min if sleep else None,
        "workout_count": workout_count,
        "workout_volume": workout_volume,
        "steps": steps,
        "habits_completed": habits_done,
        "habits_total": len(habits),
        "weight": weight,
        "targets": targets,
        "schedule": events,
    }


async def weekly_summary(db: AsyncSession, user: User, end: date | None = None) -> dict:
    end = end or user_today(user.timezone)
    start = week_start(end)
    return await _range_summary(db, user, start, end)


async def monthly_summary(db: AsyncSession, user: User, end: date | None = None) -> dict:
    end = end or user_today(user.timezone)
    start = end.replace(day=1)
    return await _range_summary(db, user, start, end)


async def range_summary(db: AsyncSession, user: User, days: int) -> dict:
    end = user_today(user.timezone)
    start = end - timedelta(days=days - 1)
    return await _range_summary(db, user, start, end)


async def _range_summary(db: AsyncSession, user: User, start: date, end: date) -> dict:
    span = (end - start).days + 1
    nut_q = await db.execute(
        select(FoodLog.date, func.sum(FoodLog.calories), func.sum(FoodLog.protein))
        .where(FoodLog.user_id == user.id, FoodLog.date >= start, FoodLog.date <= end)
        .group_by(FoodLog.date)
    )
    nut_by_day = {d: (c or 0, p or 0) for d, c, p in nut_q.all()}
    water_q = await db.execute(
        select(WaterLog.date, func.sum(WaterLog.amount_ml)).where(
            WaterLog.user_id == user.id, WaterLog.date >= start, WaterLog.date <= end
        ).group_by(WaterLog.date)
    )
    water_by_day = dict(water_q.all())
    sleep_avg = await health_service.sleep_average(db, user, start, end)
    workouts_q = await db.execute(
        select(WorkoutSession.date, func.count(), func.sum(WorkoutSession.total_volume)).where(
            WorkoutSession.user_id == user.id, WorkoutSession.date >= start, WorkoutSession.date <= end
        ).group_by(WorkoutSession.date)
    )
    workout_days = workouts_q.all()
    workout_count = sum(r[1] for r in workout_days)
    workout_volume = round(sum(r[2] or 0 for r in workout_days), 1)

    targets = await goals_service.targets_map(db, user)
    cal_target = targets.get("calories")
    protein_target = targets.get("protein")
    days_logged = len(nut_by_day)
    cal_adherent = sum(1 for c, _ in nut_by_day.values()
                       if cal_target and 0.7 * cal_target <= c <= 1.3 * cal_target)
    protein_adherent = sum(1 for _, p in nut_by_day.values() if protein_target and p >= protein_target)
    habits = await habits_service.habit_progress(db, user, days=span)
    habit_adherence = (round(sum(h["adherence"] for h in habits) / len(habits), 3)) if habits else None
    trend = await health_service.weight_trend(db, user, start, end)

    return {
        "start": start, "end": end, "days": span,
        "avg_calories": round(sum(c for c, _ in nut_by_day.values()) / days_logged, 1) if days_logged else None,
        "avg_protein": round(sum(p for _, p in nut_by_day.values()) / days_logged, 1) if days_logged else None,
        "days_food_logged": days_logged,
        "avg_water_ml": round(sum(water_by_day.values()) / len(water_by_day), 1) if water_by_day else None,
        "avg_sleep_minutes": sleep_avg,
        "workout_count": workout_count,
        "workout_volume": workout_volume,
        "targets": targets,
        "calorie_adherence": round(cal_adherent / days_logged, 3) if days_logged and cal_target else None,
        "protein_adherence": round(protein_adherent / days_logged, 3) if days_logged and protein_target else None,
        "habit_adherence": habit_adherence,
        "weight": trend,
        "daily_calories": [{"date": d, "calories": round(c, 1), "protein": round(p, 1)}
                           for d, (c, p) in sorted(nut_by_day.items())],
    }
