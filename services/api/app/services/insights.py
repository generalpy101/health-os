"""Track D — stall detector: flat weight trend despite an active weight goal.

Applies only with an active weight_loss/weight_gain goal and >=14 days of weight
points in the last 21 days. All thresholds are deterministic constants below.
"""

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Target, User
from ..utils import metrics
from ..utils.time import user_today
from . import analytics as analytics_service
from . import goals as goals_service
from . import health as health_service

WINDOW_DAYS = 21
MIN_WEIGHT_DAYS = 14
FLAT_RATE_KG_WK = 0.05  # |weekly_rate| below this counts as stalled
ADHERENCE_OK = 0.7      # weekly calorie/protein adherence at or above this is fine
SLEEP_OK_RATIO = 0.9    # avg sleep within 90% of target is fine


async def _weekly_target(db: AsyncSession, user: User, key: str) -> float | None:
    result = await db.execute(
        select(Target).where(Target.user_id == user.id, Target.key == key,
                             Target.period == "weekly", Target.active.is_(True)).limit(1)
    )
    target = result.scalar_one_or_none()
    return target.value if target else None


def _fmt_minutes(minutes: float) -> str:
    return f"{minutes / 60:g}h" if minutes >= 90 else f"{minutes:g}min"


async def stall_check(db: AsyncSession, user: User) -> dict:
    goals = await goals_service.list_goals(db, user, status_filter="active")
    goal = next((g for g in goals if g.type in ("weight_loss", "weight_gain")), None)
    today = user_today(user.timezone)
    start = today - timedelta(days=WINDOW_DAYS - 1)
    rows = await health_service.list_measurements(db, user, type_="weight", start=start, end=today, limit=500)
    by_day: dict[date, list[float]] = {}
    for r in rows:
        by_day.setdefault(r.date, []).append(r.value)
    days_with = len(by_day)
    weeks_tracked = round(days_with / 7, 1)

    if goal is None or days_with < MIN_WEIGHT_DAYS:
        return {"applies": False, "stalled": False, "weekly_rate": None,
                "weeks_tracked": weeks_tracked, "factors": [], "suggestion": ""}

    points = [(d, sum(vs) / len(vs)) for d, vs in sorted(by_day.items())]
    slope = metrics.linear_trend(points)
    weekly_rate = round(slope * 7, 3) if slope is not None else None
    stalled = weekly_rate is not None and abs(weekly_rate) < FLAT_RATE_KG_WK

    weekly = await analytics_service.weekly_summary(db, user)
    targets = weekly["targets"]
    workouts_target = await _weekly_target(db, user, "workouts")
    sleep_target = targets.get("sleep_minutes")

    factors: list[dict] = []  # carries a private "display" for the suggestion; stripped at return
    cal = weekly["calorie_adherence"]
    factors.append({
        "label": "Calories", "value": cal,
        "verdict": "ok" if cal is not None and cal >= ADHERENCE_OK else "low",
        "display": (f"{round(cal * 100)}% adherence" if cal is not None
                    else "no calorie target" if targets.get("calories") is None else "not logged this week"),
    })
    pro = weekly["protein_adherence"]
    factors.append({
        "label": "Protein", "value": pro,
        "verdict": "ok" if pro is not None and pro >= ADHERENCE_OK else "low",
        "display": (f"{round(pro * 100)}% adherence" if pro is not None
                    else "no protein target" if targets.get("protein") is None else "not logged this week"),
    })
    workouts = weekly["workout_count"]
    if workouts_target:
        factors.append({
            "label": "Workouts", "value": round(workouts / workouts_target, 2),
            "verdict": "ok" if workouts >= workouts_target else "low",
            "display": f"{workouts}/{workouts_target:g} sessions this week",
        })
    else:
        factors.append({"label": "Workouts", "value": None, "verdict": "ok",
                        "display": f"{workouts} this week"})
    avg_sleep = weekly["avg_sleep_minutes"]
    if sleep_target and avg_sleep is not None:
        ratio = round(avg_sleep / sleep_target, 2)
        factors.append({
            "label": "Sleep", "value": ratio,
            "verdict": "ok" if ratio >= SLEEP_OK_RATIO else "low",
            "display": f"avg {_fmt_minutes(round(avg_sleep))} vs {_fmt_minutes(round(sleep_target))} target",
        })
    elif sleep_target:
        factors.append({"label": "Sleep", "value": None, "verdict": "low", "display": "not logged this week"})
    else:
        factors.append({"label": "Sleep", "value": None, "verdict": "ok", "display": "no target"})

    if not stalled:
        rate_txt = f"{weekly_rate:+.2f}" if weekly_rate is not None else "0"
        suggestion = f"Weight is moving at {rate_txt} kg/week — no stall. Keep the current plan."
    else:
        direction = "cutting" if goal.type == "weight_loss" else "adding"
        lows = sorted((f for f in factors if f["verdict"] == "low"),
                      key=lambda f: f["value"] if f["value"] is not None else -1)
        if not lows:
            tail = ("Adherence looks solid across the board — hold course for another week "
                    "before changing calories.")
        elif len(lows) == 1:
            tail = (f"{lows[0]['label']}: {lows[0]['display']} — that's the weak link; "
                    f"tighten it before {direction} calories.")
        else:
            tail = (f"{lows[0]['label']} ({lows[0]['display']}) and "
                    f"{lows[1]['label'].lower()} ({lows[1]['display']}) are the weak links — "
                    f"tighten those before {direction} calories.")
        suggestion = f"Weight flat for {weeks_tracked:g} weeks. {tail}"

    return {
        "applies": True,
        "stalled": stalled,
        "weekly_rate": weekly_rate,
        "weeks_tracked": weeks_tracked,
        "factors": [{k: f[k] for k in ("label", "value", "verdict")} for f in factors],
        "suggestion": suggestion,
    }
