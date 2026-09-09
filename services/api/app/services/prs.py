"""Track D — personal records derived from workout_sessions.exercises JSONB.

All math is deterministic: best weight = max set weight with reps > 0;
best volume set = max(weight * reps). Exercise identity is the lowercased,
stripped name; the most recent casing is what gets displayed.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import User, WorkoutSession


def _key(name: str) -> str:
    return name.strip().lower()


def _weighted_sets(exercise: dict):
    """Yield (weight, reps) for sets that count toward PRs: weight > 0, reps > 0."""
    for s in exercise.get("sets", []) or []:
        w = s.get("weight")
        r = s.get("reps")
        if w is None or r is None:
            continue
        w, r = float(w), float(r)
        if w > 0 and r > 0:
            yield w, r


def exercise_bests(sessions: list[WorkoutSession]) -> dict[str, dict]:
    """Per-exercise records over sessions (any order). Deterministic ties: the
    earliest session achieving the max keeps the date."""
    ordered = sorted(sessions, key=lambda s: (s.date, s.created_at))
    bests: dict[str, dict] = {}
    for session in ordered:
        when = (session.date, session.created_at)
        for ex in session.exercises or []:
            name = (ex.get("name") or "").strip()
            if not name:
                continue
            k = _key(name)
            rec = bests.setdefault(k, {
                "exercise": name, "best_weight": None, "reps_at_best": None,
                "best_volume_set": None, "date": None, "_best_at": None, "_latest_at": None,
            })
            rec["_latest_at"] = when  # ascending -> last write is the latest session
            rec["exercise"] = name  # latest casing
            for w, r in _weighted_sets(ex):
                if rec["best_weight"] is None or w > rec["best_weight"]:
                    rec["best_weight"] = w
                    rec["reps_at_best"] = r
                    rec["date"] = session.date
                    rec["_best_at"] = when
                vol = w * r
                if rec["best_volume_set"] is None or vol > rec["best_volume_set"]:
                    rec["best_volume_set"] = round(vol, 1)
    for rec in bests.values():
        rec["is_recent"] = rec["_best_at"] is not None and rec["_best_at"] == rec["_latest_at"]
    return bests


async def personal_records(db: AsyncSession, user: User) -> list[dict]:
    result = await db.execute(
        select(WorkoutSession).where(WorkoutSession.user_id == user.id)
    )
    bests = exercise_bests(list(result.scalars().all()))
    rows = [
        {k: rec[k] for k in ("exercise", "best_weight", "reps_at_best", "best_volume_set", "date", "is_recent")}
        for rec in bests.values()
        if rec["best_weight"] is not None  # lifting records only
    ]
    rows.sort(key=lambda r: r["exercise"].lower())
    return rows


def detect_new_prs(prior_sessions: list[WorkoutSession], new_exercises: list[dict]) -> list[dict]:
    """Compare the new session's per-exercise bests against all prior sessions."""
    prior = exercise_bests(prior_sessions)
    out: list[dict] = []
    for ex in new_exercises or []:
        name = (ex.get("name") or "").strip()
        if not name:
            continue
        rec = prior.get(_key(name))
        best_w = None
        best_vol = None
        for w, r in _weighted_sets(ex):
            if best_w is None or w > best_w:
                best_w = w
            vol = round(w * r, 1)
            if best_vol is None or vol > best_vol:
                best_vol = vol
        prev_w = rec["best_weight"] if rec else None
        if best_w is not None and (prev_w is None or best_w > prev_w):
            out.append({"exercise": name, "kind": "weight", "value": best_w, "previous": prev_w})
        prev_v = rec["best_volume_set"] if rec else None
        if best_vol is not None and (prev_v is None or best_vol > prev_v):
            out.append({"exercise": name, "kind": "volume", "value": best_vol, "previous": prev_v})
    return out
