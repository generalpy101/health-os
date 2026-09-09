"""Evening coach check-in: today's real numbers → one fix for tomorrow.

Deterministic core always; when the user's provider is a real LLM, it polishes
the message (never changes the numbers). Saved as a Recommendation (visible in
the dashboard widget) and pushed when the user has push enabled.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from ..ai.provider import MockProvider
from ..ai.registry import provider_for_user
from ..models import Recommendation, User
from ..utils.time import user_now
from . import analytics as analytics_service
from . import goals as goals_service

PROMPT = """You are the user's coach writing a 9 PM check-in. 2-3 short sentences, plain text, no emoji,
no medical advice. Use ONLY the numbers given — never invent any. Structure: what went well,
what slipped (if anything), the single most useful thing to do tomorrow.

DATA:
%s"""


def _deterministic(summary: dict, targets: dict) -> str:
    n = summary["nutrition"]
    lines = []
    cal_t = targets.get("calories")
    pro_t = targets.get("protein")
    if cal_t:
        pct = n["calories"] / cal_t
        lines.append(f"Calories: {n['calories']:.0f} of {cal_t:.0f} "
                     f"({'right in range' if 0.75 <= pct <= 1.15 else 'under' if pct < 0.75 else 'over'}).")
    if pro_t:
        pct = n["protein"] / pro_t
        lines.append(f"Protein: {n['protein']:.0f}g of {pro_t:.0f}g "
                     f"({'hit' if pct >= 0.95 else f'{pct:.0%} — short' if pct < 0.8 else 'close'}).")
    if targets.get("water"):
        lines.append(f"Water: {summary['water_ml']:.0f}ml of {targets['water']:.0f}ml.")
    if summary["sleep_minutes"]:
        lines.append(f"Sleep last night: {summary['sleep_minutes'] // 60}h {summary['sleep_minutes'] % 60}m.")
    if summary["workout_count"]:
        lines.append("Training done today. Recovery matters tonight.")
    if summary["habits_total"]:
        lines.append(f"Habits: {summary['habits_completed']}/{summary['habits_total']}.")

    # one fix: the biggest percentage gap among tracked targets
    gaps = []
    if pro_t and n["protein"] / pro_t < 1:
        gaps.append((n["protein"] / pro_t, "front-load protein earlier tomorrow — don't leave it for the last meal"))
    if targets.get("water") and summary["water_ml"] / targets["water"] < 1:
        gaps.append((summary["water_ml"] / targets["water"], "keep a bottle at your desk from the morning"))
    if targets.get("sleep_minutes") and summary["sleep_minutes"] and summary["sleep_minutes"] < targets["sleep_minutes"] * 0.9:
        gaps.append((summary["sleep_minutes"] / targets["sleep_minutes"], "start winding down 30 minutes earlier"))
    if not lines:
        return "Quiet day on the tracker — log tomorrow and I'll have something useful to say."
    fix = f"Tomorrow: {min(gaps)[1]}." if gaps else "Tomorrow: same again — consistency is the whole game."
    return " ".join(lines[:3]) + " " + fix


async def run_checkin(db: AsyncSession, user: User) -> None:
    summary = await analytics_service.daily_summary(db, user)
    targets = await goals_service.targets_map(db, user)
    text = _deterministic(summary, targets)

    provider = await provider_for_user(db, user)
    if not isinstance(provider, MockProvider):
        try:
            import json
            resp = await provider.complete([{"role": "user", "content": PROMPT % json.dumps({
                "calories": summary["nutrition"]["calories"], "protein": summary["nutrition"]["protein"],
                "water_ml": summary["water_ml"], "sleep_minutes": summary["sleep_minutes"],
                "workout_count": summary["workout_count"],
                "habits_completed": summary["habits_completed"], "habits_total": summary["habits_total"],
                "targets": targets,
            }, default=str)}], tools=None)
            if resp.text.strip():
                text = resp.text.strip()[:500]
        except Exception:
            pass  # deterministic text stands

    now = user_now(user.timezone)
    db.add(Recommendation(
        user_id=user.id, title="Evening check-in", reason=text, priority="high",
        confidence=0.9, source="coach",
        expires_at=now.replace(hour=23, minute=59).astimezone(__import__("datetime").timezone.utc),
        actions=[],
    ))
    await db.commit()

    # push when enabled
    try:
        from . import push as push_service
        await push_service.send_to_user(db, user, "Evening check-in", text[:140], url="/today")
    except Exception:
        pass
