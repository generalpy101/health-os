"""Deterministic health/nutrition math. AI output is never trusted for these."""

from datetime import date


def scale_nutrients(food: dict, quantity: float, unit: str = "g") -> dict:
    """Scale a food's per-serving nutrients to the requested quantity.

    Foods store nutrients per `serving_size`/`serving_unit`. Quantity given in
    grams/ml scales linearly; quantity in 'serving' units multiplies directly.
    """
    serving = float(food.get("serving_size") or 100)
    if unit in ("serving", "servings", "portion", "piece", "pcs"):
        factor = quantity
    else:  # treat g/ml/oz-ish amounts as linear against serving size
        factor = quantity / serving if serving else 0.0
    return {
        "calories": round(float(food.get("calories", 0)) * factor, 1),
        "protein": round(float(food.get("protein", 0)) * factor, 1),
        "carbs": round(float(food.get("carbs", 0)) * factor, 1),
        "fat": round(float(food.get("fat", 0)) * factor, 1),
        "fiber": round(float(food.get("fiber", 0)) * factor, 1),
    }


def sum_items(items: list[dict]) -> dict:
    """Sum nutrient snapshot fields across log/recipe items."""
    totals = {"calories": 0.0, "protein": 0.0, "carbs": 0.0, "fat": 0.0, "fiber": 0.0}
    for item in items or []:
        for key in totals:
            totals[key] += float(item.get(key) or 0)
    return {k: round(v, 1) for k, v in totals.items()}


def recipe_nutrition_per_serving(ingredients: list[dict], servings: float) -> dict:
    total = sum_items(ingredients)
    s = servings if servings and servings > 0 else 1
    return {
        "total": total,
        "per_serving": {k: round(v / s, 1) for k, v in total.items()},
    }


def bmi(weight_kg: float, height_cm: float) -> float | None:
    if weight_kg <= 0 or height_cm <= 0:
        return None
    h = height_cm / 100
    return round(weight_kg / (h * h), 1)


def bmr_mifflin(weight_kg: float, height_cm: float, age: int, sex: str | None) -> float | None:
    if weight_kg <= 0 or height_cm <= 0 or age <= 0:
        return None
    base = 10 * weight_kg + 6.25 * height_cm - 5 * age
    if sex and sex.lower().startswith("f"):
        base -= 161
    else:
        base += 5
    return round(base)


ACTIVITY_FACTORS = {
    "sedentary": 1.2,
    "light": 1.375,
    "moderate": 1.55,
    "active": 1.725,
    "very_active": 1.9,
}


def tdee(bmr: float | None, activity_level: str | None) -> float | None:
    if bmr is None:
        return None
    factor = ACTIVITY_FACTORS.get((activity_level or "moderate"), 1.55)
    return round(bmr * factor)


def moving_average(points: list[tuple[date, float]], window: int = 7) -> list[tuple[date, float]]:
    """Trailing moving average over (date, value) points sorted by date."""
    out: list[tuple[date, float]] = []
    values: list[float] = []
    for d, v in sorted(points, key=lambda p: p[0]):
        values.append(v)
        window_vals = values[-window:]
        out.append((d, round(sum(window_vals) / len(window_vals), 2)))
    return out


def linear_trend(points: list[tuple[date, float]]) -> float | None:
    """Slope (units/day) of least-squares fit over time series."""
    pts = sorted(points, key=lambda p: p[0])
    n = len(pts)
    if n < 2:
        return None
    x0 = pts[0][0].toordinal()
    xs = [p[0].toordinal() - x0 for p in pts]
    ys = [p[1] for p in pts]
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    denom = sum((x - mean_x) ** 2 for x in xs)
    if denom == 0:
        return 0.0
    slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / denom
    return round(slope, 4)


def adherence(actual: float, target: float, mode: str = "minimum") -> float:
    """0..1 adherence of an actual value against a target."""
    if target <= 0:
        return 0.0
    if mode == "maximum":
        return round(min(1.0, target / actual), 3) if actual > 0 else 1.0
    return round(min(1.0, actual / target), 3)


def workout_volume(exercises: list[dict]) -> float:
    """Total tonnage (kg) = sum over sets of weight * reps."""
    total = 0.0
    for ex in exercises or []:
        for s in ex.get("sets", []) or []:
            w = float(s.get("weight") or 0)
            r = float(s.get("reps") or 0)
            total += w * r
    return round(total, 1)


def goal_progress(goal_type: str, start: float | None, target: float | None, current: float | None) -> float | None:
    """0..1 progress toward a numeric goal (handles up/down directions)."""
    if start is None or target is None or current is None or start == target:
        return None
    done = current - start
    needed = target - start
    pct = done / needed
    return round(max(0.0, min(1.0, pct)), 3)
