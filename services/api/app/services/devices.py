"""Device / shortcut ingestion (Track C).

Auth is a per-user Bearer token stored in user_preferences.data.ingest_token
(created on first read, rotatable). Every accepted event lands in
`integration_events` (idempotent via unique(user_id, source, external_id)),
then mirrors into domain tables where natural:

  weight          -> Measurement(type="weight", source="device", unit from event, default kg)
  steps           -> Activity(type="walking", source="device", steps=value, on observed local date)
  water_ml        -> WaterLog(amount_ml=value, on observed local date)  (WaterLog has no source column)
  sleep_minutes   -> event only (SleepLog needs start/end we don't get from a bare duration)
  active_calories -> event only
  heart_rate      -> event only
"""

import secrets
from datetime import datetime, timezone
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Activity, IntegrationEvent, Measurement, User, UserPreference, WaterLog
from ..schemas import IngestIn

KNOWN_METRICS = {"steps", "weight", "water_ml", "sleep_minutes", "active_calories", "heart_rate"}


async def _preferences(db: AsyncSession, user_id: UUID) -> UserPreference:
    pref = (await db.execute(
        select(UserPreference).where(UserPreference.user_id == user_id)
    )).scalar_one_or_none()
    if pref is None:
        pref = UserPreference(user_id=user_id, data={})
        db.add(pref)
        await db.flush()
    return pref


async def get_or_create_token(db: AsyncSession, user: User) -> str:
    pref = await _preferences(db, user.id)
    token = (pref.data or {}).get("ingest_token")
    if not token:
        token = secrets.token_urlsafe(24)
        pref.data = {**(pref.data or {}), "ingest_token": token}
        await db.commit()
    return token


async def rotate_token(db: AsyncSession, user: User) -> str:
    pref = await _preferences(db, user.id)
    token = secrets.token_urlsafe(24)
    pref.data = {**(pref.data or {}), "ingest_token": token}
    await db.commit()
    return token


async def user_for_ingest_token(db: AsyncSession, token: str | None) -> User | None:
    if not token:
        return None
    # JSON path lookup — compiles to ->> on Postgres, json_extract on SQLite
    pref = (await db.execute(
        select(UserPreference).where(UserPreference.data["ingest_token"].as_string() == token)
    )).scalar_one_or_none()
    if pref is None:
        return None
    return await db.get(User, pref.user_id)


def _local_date(observed_at: datetime, tz_name: str):
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=timezone.utc)
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = timezone.utc
    return observed_at.astimezone(tz).date()


async def ingest(db: AsyncSession, user: User, data: IngestIn) -> dict:
    accepted = duplicates = rejected = 0
    for ev in data.events:
        if ev.metric not in KNOWN_METRICS:
            rejected += 1  # unknown metric — skipped, surfaced in the response
            continue
        if ev.external_id:
            existing = await db.execute(
                select(IntegrationEvent.id).where(
                    IntegrationEvent.user_id == user.id,
                    IntegrationEvent.source == data.source,
                    IntegrationEvent.external_id == ev.external_id,
                )
            )
            if existing.scalar_one_or_none() is not None:
                duplicates += 1
                continue
        row = IntegrationEvent(
            user_id=user.id, source=data.source, external_id=ev.external_id,
            metric=ev.metric, value=ev.value, unit=ev.unit, observed_at=ev.observed_at,
            raw=ev.model_dump(mode="json"),
        )
        db.add(row)
        _mirror(db, user, ev.metric, ev.value, ev.unit, ev.observed_at)
        accepted += 1
    await db.commit()
    return {"accepted": accepted, "duplicates": duplicates, "rejected": rejected}


def _mirror(db: AsyncSession, user: User, metric: str, value: float, unit: str | None,
            observed_at: datetime) -> None:
    day = _local_date(observed_at, user.timezone)
    if metric == "weight":
        db.add(Measurement(user_id=user.id, type="weight", value=value, unit=unit or "kg",
                           date=day, measured_at=observed_at, source="device"))
    elif metric == "steps":
        db.add(Activity(user_id=user.id, type="walking", date=day, steps=int(value),
                        source="device"))
    elif metric == "water_ml":
        db.add(WaterLog(user_id=user.id, date=day, amount_ml=value))
