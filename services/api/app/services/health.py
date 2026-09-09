from datetime import date, timedelta, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Measurement, SleepLog, User, WaterLog
from ..schemas import MeasurementIn, SleepIn, WaterIn
from ..utils import metrics
from ..utils.time import parse_date
from .common import audit, get_owned


# ---------- water ----------

async def _water_for_day(db: AsyncSession, user: User, day: date) -> list[WaterLog]:
    """Water logs for the calendar day, or the user's custom day window when set."""
    from ..utils.time import day_window
    from .common import day_start_minutes

    win = day_window(day, user.timezone, await day_start_minutes(db, user))
    if win is None:
        result = await db.execute(
            select(WaterLog).where(WaterLog.user_id == user.id, WaterLog.date == day)
            .order_by(WaterLog.created_at.desc())
        )
        return list(result.scalars().all())
    start, end = win
    start_utc = start.astimezone(timezone.utc)
    end_utc = end.astimezone(timezone.utc)
    result = await db.execute(
        select(WaterLog).where(WaterLog.user_id == user.id, WaterLog.date.in_([day, day + timedelta(days=1)]))
        .order_by(WaterLog.created_at.desc())
    )
    out = []
    for log in result.scalars().all():
        ts = log.created_at if log.created_at.tzinfo else log.created_at.replace(tzinfo=timezone.utc)
        if start_utc <= ts < end_utc:
            out.append(log)
    return out


async def log_water(db: AsyncSession, user: User, data: WaterIn) -> WaterLog:
    log = WaterLog(user_id=user.id, date=parse_date(data.date, user.timezone), amount_ml=data.amount_ml)
    db.add(log)
    await db.commit()
    await db.refresh(log)
    return log


async def water_total(db: AsyncSession, user: User, day: date) -> float:
    return round(sum(l.amount_ml for l in await _water_for_day(db, user, day)), 1)


async def list_water(db: AsyncSession, user: User, day: date) -> list[WaterLog]:
    return await _water_for_day(db, user, day)


async def delete_water(db: AsyncSession, user: User, log_id: UUID) -> None:
    log = await get_owned(db, WaterLog, log_id, user)
    await db.delete(log)
    await db.commit()


# ---------- sleep ----------

async def log_sleep(db: AsyncSession, user: User, data: SleepIn, source: str = "manual") -> SleepLog:
    duration = int((data.sleep_end - data.sleep_start).total_seconds() / 60)
    if duration <= 0:
        from fastapi import HTTPException
        raise HTTPException(422, "sleep_end must be after sleep_start")
    log = SleepLog(
        user_id=user.id,
        date=parse_date(data.date, user.timezone) if data.date else data.sleep_end.date(),
        sleep_start=data.sleep_start, sleep_end=data.sleep_end, duration_min=duration,
        quality=data.quality, interruptions=data.interruptions, notes=data.notes, source=source,
    )
    db.add(log)
    await audit(db, user.id, "sleep_logged", "sleep_log", log.id, {"duration_min": duration})
    await db.commit()
    await db.refresh(log)
    return log


async def list_sleep(db: AsyncSession, user: User, start: date | None = None, end: date | None = None,
                     limit: int = 60) -> list[SleepLog]:
    stmt = select(SleepLog).where(SleepLog.user_id == user.id)
    if start:
        stmt = stmt.where(SleepLog.date >= start)
    if end:
        stmt = stmt.where(SleepLog.date <= end)
    result = await db.execute(stmt.order_by(SleepLog.date.desc()).limit(min(limit, 200)))
    return list(result.scalars().all())


async def delete_sleep(db: AsyncSession, user: User, log_id: UUID) -> None:
    log = await get_owned(db, SleepLog, log_id, user)
    await db.delete(log)
    await db.commit()


async def sleep_average(db: AsyncSession, user: User, start: date, end: date) -> float | None:
    result = await db.execute(
        select(func.avg(SleepLog.duration_min)).where(
            SleepLog.user_id == user.id, SleepLog.date >= start, SleepLog.date <= end
        )
    )
    avg = result.scalar_one_or_none()
    return round(float(avg), 1) if avg is not None else None


# ---------- measurements ----------

async def record_measurement(db: AsyncSession, user: User, data: MeasurementIn, source: str = "manual") -> Measurement:
    m = Measurement(user_id=user.id, date=parse_date(data.date, user.timezone), source=source,
                    **data.model_dump(exclude={"date"}))
    db.add(m)
    await audit(db, user.id, "measurement_recorded", "measurement", m.id,
                {"type": m.type, "value": m.value, "unit": m.unit})
    await db.commit()
    await db.refresh(m)
    return m


async def list_measurements(db: AsyncSession, user: User, type_: str | None = None,
                            start: date | None = None, end: date | None = None,
                            limit: int = 100, offset: int = 0) -> list[Measurement]:
    stmt = select(Measurement).where(Measurement.user_id == user.id)
    if type_:
        stmt = stmt.where(Measurement.type == type_)
    if start:
        stmt = stmt.where(Measurement.date >= start)
    if end:
        stmt = stmt.where(Measurement.date <= end)
    result = await db.execute(
        stmt.order_by(Measurement.date.asc(), Measurement.created_at.asc()).limit(min(limit, 500)).offset(offset)
    )
    return list(result.scalars().all())


async def delete_measurement(db: AsyncSession, user: User, m_id: UUID) -> None:
    m = await get_owned(db, Measurement, m_id, user)
    await db.delete(m)
    await db.commit()


async def weight_trend(db: AsyncSession, user: User, start: date, end: date) -> dict:
    rows = await list_measurements(db, user, type_="weight", start=start, end=end, limit=500)
    # one value per day (mean of that day)
    by_day: dict[date, list[float]] = {}
    for r in rows:
        by_day.setdefault(r.date, []).append(r.value)
    points = [(d, sum(vs) / len(vs)) for d, vs in sorted(by_day.items())]
    ma = metrics.moving_average(points, window=7)
    slope = metrics.linear_trend(points)
    return {
        "points": [{"date": d, "value": round(v, 2)} for d, v in points],
        "moving_average": [{"date": d, "value": v} for d, v in ma],
        "slope_per_day": slope,
        "weekly_rate": round(slope * 7, 3) if slope is not None else None,
    }
