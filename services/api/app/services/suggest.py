"""Deterministic "what should I eat now" engine.

Ranks the user's own recipes and saved meals against what's left of today's
targets, pantry coverage, and how often they actually eat them. The AI may
explain these, but it never invents the ranking.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from ..models import User
from . import analytics as analytics_service
from . import goals as goals_service
from . import pantry as pantry_service
from . import saved_meals as saved_meals_service
from .recipes import list_recipes


async def meal_suggestions(db: AsyncSession, user: User, limit: int = 3) -> dict:
    summary = await analytics_service.daily_summary(db, user)
    targets = await goals_service.targets_map(db, user)
    cal_t, pro_t = targets.get("calories"), targets.get("protein")
    if not cal_t and not pro_t:
        return {"suggestions": [],
                "message": "Set calorie/protein targets first (Settings → Daily targets) — then I can rank what fits."}

    today_cal = summary["nutrition"]["calories"]
    today_pro = summary["nutrition"]["protein"]
    rem_cal = (cal_t - today_cal) if cal_t else None
    rem_pro = (pro_t - today_pro) if pro_t else None

    # pantry coverage map when the user keeps a pantry
    coverage: dict[str, float] = {}
    try:
        pantry_items = await pantry_service.list_items(db, user)
        if pantry_items:
            for m in await pantry_service.recipe_matches(db, user):
                coverage[m["recipe_id"]] = m["coverage"]
    except Exception:
        pass

    frequent = {f["name"].lower(): f["uses"] for f in await saved_meals_service.frequent_foods(db, user, 20)}

    candidates: list[dict] = []
    for r in await list_recipes(db, user, limit=100):
        n = (r.nutrition or {}).get("per_serving") or {}
        candidates.append({
            "kind": "recipe", "id": str(r.id), "name": r.name,
            "calories": n.get("calories", 0), "protein": n.get("protein", 0),
            "coverage": coverage.get(str(r.id)),
            "tags": r.tags or [],
        })
    for m in await saved_meals_service.list_saved_meals(db, user):
        cal = sum(i.get("calories", 0) for i in (m.items or []))
        pro = sum(i.get("protein", 0) for i in (m.items or []))
        candidates.append({
            "kind": "saved_meal", "id": str(m.id), "name": m.name,
            "calories": round(cal, 1), "protein": round(pro, 1),
            "coverage": None, "tags": [],
            "uses": m.use_count,
        })

    if not candidates:
        return {"suggestions": [],
                "message": "No recipes or saved meals yet — create a recipe (or ask me to) and suggestions appear here."}

    max_protein = max((c["protein"] for c in candidates), default=1) or 1
    protein_hungry = bool(rem_pro and rem_pro > 0 and (not rem_cal or rem_pro / max(rem_cal, 1) > 0.06))

    scored = []
    for c in candidates:
        reasons = []
        score = 0.0
        if protein_hungry and c["protein"]:
            score += 0.45 * (c["protein"] / max_protein)
            if c["protein"] >= 25:
                reasons.append(f"{c['protein']:.0f}g protein — you're {rem_pro:.0f}g short today")
        if rem_cal and rem_cal > 0 and c["calories"]:
            fit = max(0.0, 1 - abs(c["calories"] - rem_cal) / rem_cal)
            score += 0.3 * fit
            if c["calories"] <= rem_cal * 1.1:
                reasons.append(f"fits your remaining ~{rem_cal:.0f} kcal")
            else:
                score -= 0.25
        if c.get("coverage"):
            score += 0.2 * c["coverage"]
            if c["coverage"] >= 0.8:
                reasons.append("you have everything at home")
        uses = c.get("uses") or frequent.get(c["name"].lower(), 0)
        if uses:
            score += min(0.15, 0.03 * uses)
            reasons.append("one of your regulars")
        scored.append((score, c, reasons))

    scored.sort(key=lambda x: -x[0])
    out = []
    for score, c, reasons in scored[:limit]:
        out.append({
            **c,
            "score": round(score, 3),
            "reason": reasons[0] if reasons else "balanced pick for what's left today",
        })
    return {
        "suggestions": out,
        "remaining": {"calories": round(rem_cal, 1) if rem_cal is not None else None,
                      "protein": round(rem_pro, 1) if rem_pro is not None else None},
    }
