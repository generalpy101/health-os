"""In-app notifications, computed fresh from real data on read.

No noisy push pipeline: a notification exists only while it's true and actionable.
Quiet hours (user preference data.notifications = {"quiet_from": 22, "quiet_to": 7})
suppress non-urgent items.
"""

from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..deps import current_user
from ..models import User
from ..services import analytics as analytics_service
from ..services import goals as goals_service
from ..services import habits as habits_service
from ..services import schedule as schedule_service
from ..utils.time import user_now, user_today

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("")
async def get_notifications(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    from ..models import UserPreference
    from sqlalchemy import select

    pref = (await db.execute(select(UserPreference).where(UserPreference.user_id == user.id))).scalar_one_or_none()
    notif_pref = ((pref.data if pref else {}) or {}).get("notifications") or {}
    now = user_now(user.timezone)
    hour = now.hour
    qf, qt = notif_pref.get("quiet_from"), notif_pref.get("quiet_to")
    quiet = False
    if qf is not None and qt is not None:
        quiet = (hour >= qf or hour < qt) if qf > qt else (qf <= hour < qt)

    items: list[dict] = []
    today = user_today(user.timezone)
    events = await schedule_service.get_schedule(db, user, today, today)
    for e in events:
        mins = (e["start_at"] - now).total_seconds() / 60
        if 0 <= mins <= 180:
            items.append({
                "kind": "schedule", "priority": "high", "title": e["title"],
                "reason": f"Starts in {int(mins)} min" if mins > 5 else "Starting now",
                "href": "/schedule",
            })

    summary = await analytics_service.daily_summary(db, user)
    targets = await goals_service.targets_map(db, user)
    if not quiet:
        if summary["habits_total"] > summary["habits_completed"] and hour >= 17:
            items.append({
                "kind": "habit", "priority": "medium",
                "title": f"{summary['habits_total'] - summary['habits_completed']} habit(s) still open",
                "reason": "Evening check-in — close them out.", "href": "/today",
            })
        water_t = targets.get("water")
        if water_t and summary["water_ml"] < water_t * 0.4 and hour >= 14:
            items.append({
                "kind": "water", "priority": "medium", "title": "Hydration is behind",
                "reason": f"{summary['water_ml']:.0f}ml of {water_t:.0f}ml so far.", "href": "/today",
            })
    return {"notifications": items, "quiet_hours_active": quiet, "count": len(items)}
