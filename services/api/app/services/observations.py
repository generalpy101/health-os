"""Deterministic behavior learning (spec §35/§124): repeated behavior -> memory records.

Runs daily via the worker. Never creates 'facts' — observations keep source="behavior"
and a confidence derived from evidence counts, so the AI weighs them appropriately
and they stay reviewable/deletable in Settings.
"""

from datetime import timedelta
from statistics import median

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import FoodLog, User, UserMemory, WorkoutSession
from ..utils.time import user_today


async def _upsert_memory(db: AsyncSession, user_id, key: str, value, confidence: float,
                         evidence_count: int) -> None:
    existing = (await db.execute(
        select(UserMemory).where(UserMemory.user_id == user_id, UserMemory.key == key,
                                 UserMemory.source == "behavior")
    )).scalar_one_or_none()
    payload = {"value": value, "evidence_count": evidence_count}
    if existing:
        existing.value = payload
        existing.confidence = confidence
        existing.status = "active"
    else:
        db.add(UserMemory(user_id=user_id, type="preference", key=key, value=payload,
                          source="behavior", confidence=confidence, status="active"))


async def extract_observations(db: AsyncSession, user: User) -> int:
    """Mine the last 30 days of logs. Returns how many observations were written."""
    since = user_today(user.timezone) - timedelta(days=30)
    written = 0

    # --- frequently eaten foods (top 3 by log count) ---
    logs = (await db.execute(
        select(FoodLog).where(FoodLog.user_id == user.id, FoodLog.date >= since)
    )).scalars().all()
    counts: dict[str, int] = {}
    for log in logs:
        for item in log.items or []:
            name = (item.get("name") or "").strip().lower()
            if name and not item.get("unmatched"):
                counts[name] = counts.get(name, 0) + 1
    top = sorted(counts.items(), key=lambda kv: -kv[1])[:3]
    if top and top[0][1] >= 3:
        await _upsert_memory(db, user.id, "frequently_eats",
                             [n for n, _ in top],
                             confidence=min(0.95, 0.5 + 0.05 * top[0][1]),
                             evidence_count=top[0][1])
        written += 1

    # --- preferred workout time ---
    sessions = (await db.execute(
        select(WorkoutSession.created_at).where(WorkoutSession.user_id == user.id)
    )).scalars().all()
    if len(sessions) >= 4:
        hours = [s.hour for s in sessions if s]
        if hours:
            h = int(median(hours))
            bucket = ("night" if h < 5 else "morning" if h < 12 else
                      "afternoon" if h < 17 else "evening" if h < 22 else "night")
            await _upsert_memory(db, user.id, "preferred_workout_time", bucket,
                                 confidence=min(0.95, 0.5 + 0.05 * len(hours)),
                                 evidence_count=len(hours))
            written += 1

    # --- breakfast skipping (only when there's enough food-logging history) ---
    days_logged = {l.date for l in logs}
    breakfast_days = {l.date for l in logs if l.meal_type in ("breakfast", "brunch")}
    if len(days_logged) >= 5:
        rate = len(breakfast_days) / len(days_logged)
        if rate < 0.3:
            await _upsert_memory(db, user.id, "skips_breakfast", True,
                                 confidence=min(0.9, 0.5 + len(days_logged) * 0.03),
                                 evidence_count=len(days_logged))
            written += 1

    return written
