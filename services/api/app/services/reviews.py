"""Weekly/monthly AI reviews: cached analytics summary + narrative per period.

The summary numbers are computed once per period (deterministic, via analytics_service)
and cached in the `reviews` table together with an AI-written narrative. The narrative
uses the user's selected provider; the mock provider produces a deterministic template
so reviews work fully offline.

Freshness policy: GET returns the cached review. A stale weekly review (older than 20h)
lazily enqueues a `generate_review` background job and returns the cached version
meanwhile — same as the manual regenerate endpoint. Monthly reviews only regenerate on
demand (the period is still in progress until the month ends).
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..ai.provider import MockProvider
from ..ai.registry import provider_for_user
from ..models import Review, User
from ..utils.time import user_today
from . import analytics as analytics_service

KINDS = ("weekly", "monthly")
WEEKLY_STALE_AFTER = timedelta(hours=20)
MAX_NARRATIVE_WORDS = 120


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _json_safe(data: dict) -> dict:
    return json.loads(json.dumps(data, default=str))


def period_for(kind: str, today: date) -> tuple[date, date]:
    if kind == "weekly":
        return today - timedelta(days=6), today
    return today.replace(day=1), today


async def _summary(db: AsyncSession, user: User, kind: str) -> dict:
    if kind == "weekly":
        return await analytics_service.range_summary(db, user, 7)
    return await analytics_service.monthly_summary(db, user)


# ---------------------------------------------------------------------------
# Narrative
# ---------------------------------------------------------------------------

REVIEW_PROMPT = """Write a {kind} progress review for the user of a health & fitness app, based on the JSON summary below.

Rules: at most 120 words, plain text only (no markdown, no bullets), honest and direct —
no cheerleading and no filler. No medical advice or diagnoses. Only mention numbers that
are present in the data; if data is missing, say what the user should log to improve the
next review.

JSON summary:
%s"""


def _fmt_hours(minutes: float | None) -> str | None:
    if minutes is None:
        return None
    h, m = int(minutes) // 60, int(round(minutes)) % 60
    return f"{h}h {m}m" if h else f"{m}m"


def _template_narrative(kind: str, data: dict) -> str:
    """Deterministic offline narrative (mock provider). Honest, numbers-only."""
    label = "week" if kind == "weekly" else "month"
    days = data.get("days") or 0
    logged = data.get("days_food_logged") or 0
    sentences: list[str] = []

    if logged:
        avg_cal = data.get("avg_calories")
        avg_pro = data.get("avg_protein")
        bits = []
        if avg_cal is not None:
            bits.append(f"{avg_cal:,.0f} kcal")
        if avg_pro is not None:
            bits.append(f"{avg_pro:,.0f}g protein")
        sentences.append(
            f"You logged food on {logged} of {days} days this {label}"
            + (f", averaging {' and '.join(bits)} per logged day." if bits else ".")
        )
    else:
        sentences.append(f"No food was logged this {label}, so nutrition trends are unknown.")

    workouts = data.get("workout_count") or 0
    if workouts:
        volume = data.get("workout_volume") or 0
        sentences.append(f"You trained {workouts} time{'s' if workouts != 1 else ''} ({volume:,.0f} kg total volume).")
    else:
        sentences.append(f"No workouts were recorded this {label}.")

    sleep = _fmt_hours(data.get("avg_sleep_minutes"))
    if sleep:
        sentences.append(f"Average sleep was {sleep}.")
    if data.get("avg_water_ml") is not None:
        sentences.append(f"Average water intake: {data['avg_water_ml']:,.0f} ml per day.")

    weight = data.get("weight") or {}
    if weight.get("points") and weight.get("change") is not None:
        change = float(weight["change"])
        sentences.append(f"Weight moved {change:+.1f} kg over the period.")

    adherence = []
    if data.get("calorie_adherence") is not None:
        adherence.append(f"calories {round(data['calorie_adherence'] * 100)}%")
    if data.get("protein_adherence") is not None:
        adherence.append(f"protein {round(data['protein_adherence'] * 100)}%")
    if data.get("habit_adherence") is not None:
        adherence.append(f"habits {round(data['habit_adherence'] * 100)}%")
    if adherence:
        sentences.append(f"Adherence against targets: {', '.join(adherence)}.")

    if logged < days:
        sentences.append("Log every day to make the next review sharper.")
    return " ".join(sentences)


def _cap_words(text: str) -> str:
    words = text.split()
    if len(words) <= MAX_NARRATIVE_WORDS:
        return text
    return " ".join(words[:MAX_NARRATIVE_WORDS]).rstrip(",.;") + "…"


async def _narrative(db: AsyncSession, user: User, kind: str, data: dict) -> str:
    provider = await provider_for_user(db, user)
    if isinstance(provider, MockProvider):
        return _template_narrative(kind, data)
    prompt = REVIEW_PROMPT.format(kind=kind) % json.dumps(data, default=str)
    resp = await provider.complete([{"role": "user", "content": prompt}], tools=None)
    text = (resp.text or "").strip()
    if not text:  # provider produced nothing usable — stay honest, stay offline-safe
        return _template_narrative(kind, data)
    return _cap_words(text)


# ---------------------------------------------------------------------------
# Read / generate / cache
# ---------------------------------------------------------------------------

def to_out(review: Review) -> dict:
    return {
        "start": review.period_start.isoformat(),
        "end": review.period_end.isoformat(),
        "data": review.data or {},
        "narrative": review.narrative,
        "generated_at": _aware(review.generated_at).isoformat(),
    }


async def _generate(db: AsyncSession, user: User, kind: str) -> Review:
    data = _json_safe(await _summary(db, user, kind))
    start, end = date.fromisoformat(data["start"]), date.fromisoformat(data["end"])
    narrative = await _narrative(db, user, kind, data)
    review = (await db.execute(
        select(Review).where(Review.user_id == user.id, Review.kind == kind, Review.period_start == start)
    )).scalar_one_or_none()
    if review is None:
        review = Review(user_id=user.id, kind=kind, period_start=start, period_end=end)
        db.add(review)
    review.period_end = end
    review.data = data
    review.narrative = narrative
    review.generated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(review)
    return review


async def get_review(db: AsyncSession, user: User, kind: str) -> tuple[Review, bool]:
    """Return the cached review for the current period, generating on first read.

    Second element is True when a background refresh was enqueued (stale weekly).
    """
    start, _end = period_for(kind, user_today(user.timezone))
    review = (await db.execute(
        select(Review).where(Review.user_id == user.id, Review.kind == kind, Review.period_start == start)
    )).scalar_one_or_none()
    if review is None:
        return await _generate(db, user, kind), False
    if kind == "weekly" and datetime.now(timezone.utc) - _aware(review.generated_at) > WEEKLY_STALE_AFTER:
        from ..worker import enqueue  # lazy: worker imports push service
        await enqueue(db, "generate_review", {"kind": kind}, user_id=user.id)
        await db.commit()
        return review, True
    return review, False


async def regenerate_review(db: AsyncSession, user: User, kind: str) -> tuple[Review, bool]:
    """Enqueue a fresh narrative job; returns the cached version meanwhile.

    On first ever request there is nothing cached — generate inline so the
    response is complete.
    """
    start, _end = period_for(kind, user_today(user.timezone))
    review = (await db.execute(
        select(Review).where(Review.user_id == user.id, Review.kind == kind, Review.period_start == start)
    )).scalar_one_or_none()
    if review is None:
        return await _generate(db, user, kind), False
    from ..worker import enqueue
    await enqueue(db, "generate_review", {"kind": kind}, user_id=user.id)
    await db.commit()
    return review, True


async def run_generate_review(db: AsyncSession, user: User, kind: str) -> None:
    """Worker handler body for the `generate_review` job kind."""
    if kind not in KINDS:
        raise ValueError(f"unknown review kind: {kind}")
    await _generate(db, user, kind)
