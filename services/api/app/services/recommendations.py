"""Deterministic recommendations: rules over real data, never raw LLM output.

Refreshed lazily on read (no worker needed at this scale). Each recommendation
carries the numbers that justify it, so the UI can explain "why am I seeing this".
"""

from datetime import timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Recommendation, User, utcnow
from ..utils.time import user_now, user_today
from . import analytics as analytics_service
from . import goals as goals_service

REFRESH_HOURS = 6


async def refresh_recommendations(db: AsyncSession, user: User) -> None:
    recent = (await db.execute(
        select(Recommendation).where(Recommendation.user_id == user.id)
        .order_by(Recommendation.created_at.desc()).limit(1)
    )).scalar_one_or_none()
    if recent is not None:
        created = recent.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        if utcnow() - created < timedelta(hours=REFRESH_HOURS):
            return

    # expire old open recs, then regenerate from current data
    open_recs = (await db.execute(
        select(Recommendation).where(Recommendation.user_id == user.id, Recommendation.status == "open")
    )).scalars().all()
    for r in open_recs:
        r.status = "ignored"

    recs: list[dict] = []
    targets = await goals_service.targets_map(db, user)
    today = user_today(user.timezone)
    week = await analytics_service.range_summary(db, user, 7)
    daily = await analytics_service.daily_summary(db, user)

    protein_t = targets.get("protein")
    if protein_t and week["days_food_logged"] >= 2 and week["avg_protein"] is not None:
        ratio = week["avg_protein"] / protein_t
        if ratio < 0.8:
            recs.append({
                "title": f"Protein is averaging {week['avg_protein']:.0f}g vs your {protein_t:.0f}g target",
                "reason": f"7-day average protein intake is {ratio:.0%} of target.",
                "priority": "high", "confidence": 0.9,
                "actions": [{"type": "tip", "text": "Anchor each meal with a protein source — eggs, paneer, chicken, dal, whey."}],
            })

    water_t = targets.get("water")
    if water_t and daily["water_ml"] < water_t * 0.4 and user_now_hour(user) >= 14:
        recs.append({
            "title": f"Only {daily['water_ml']:.0f}ml water so far today",
            "reason": f"By early afternoon you're below 40% of your {water_t:.0f}ml target.",
            "priority": "medium", "confidence": 0.95,
            "actions": [{"type": "tip", "text": "Drink a large glass now; keep a bottle visible."}],
        })

    workouts_t = targets.get("workouts")
    if workouts_t:
        done = week["workout_count"]
        # rough expectation: prorate weekly target by elapsed week fraction
        day_of_week = today.weekday() + 1
        expected = workouts_t * day_of_week / 7
        if done < expected - 0.5:
            recs.append({
                "title": f"{done} workouts this week — target is {workouts_t:.0f}",
                "reason": f"By day {day_of_week} of the week you'd ideally have ~{expected:.0f} done.",
                "priority": "medium", "confidence": 0.8,
                "actions": [{"type": "link", "href": "/schedule", "text": "Find a slot in the planner"}],
            })

    sleep_t = targets.get("sleep_minutes")
    if sleep_t and week["avg_sleep_minutes"] is not None and week["avg_sleep_minutes"] < sleep_t * 0.85:
        recs.append({
            "title": f"Sleep averaging {week['avg_sleep_minutes'] / 60:.1f}h vs {sleep_t / 60:.1f}h target",
            "reason": "7-day average sleep is well below target; recovery drives training results.",
            "priority": "medium", "confidence": 0.85,
            "actions": [{"type": "tip", "text": "Move bedtime 30 minutes earlier this week."}],
        })

    if not week["weight"]["points"]:
        # only nudge weigh-ins if the user has a weight-affecting goal
        goals = await goals_service.list_goals(db, user, status_filter="active")
        if any(g.type in ("weight_loss", "weight_gain") for g in goals):
            recs.append({
                "title": "No weight logged recently",
                "reason": "Weight goals need regular measurements to compute trends.",
                "priority": "low", "confidence": 0.9,
                "actions": [{"type": "tip", "text": "Weigh in each morning after waking for a clean trend."}],
            })

    for r in recs:
        db.add(Recommendation(user_id=user.id, source="rules", **r))
    await db.commit()


def user_now_hour(user: User) -> int:
    return user_now(user.timezone).hour
