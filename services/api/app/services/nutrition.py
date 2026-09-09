import re
from datetime import date, datetime, timedelta, timezone
from uuid import UUID

from fastapi import HTTPException

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Food, FoodLog, User
from ..schemas import FoodIn, FoodLogIn, FoodLogItemIn
from ..utils import metrics
from ..utils.time import day_window, parse_date
from . import food_providers
from .common import audit, day_start_minutes, get_owned


async def search_foods(db: AsyncSession, user: User, query: str = "", limit: int = 20) -> list[Food]:
    stmt = select(Food).where(or_(Food.user_id == user.id, Food.user_id.is_(None)))
    if query:
        stmt = stmt.where(Food.name.ilike(f"%{query}%"))
    stmt = stmt.order_by(Food.user_id.is_(None), Food.name).limit(min(limit, 100))
    result = await db.execute(stmt)
    return list(result.scalars().all())


# ---------- TRACK A: remote food providers ----------

async def _cache_remote_foods(db: AsyncSession, rows: list[dict]) -> list[Food]:
    """Persist remote hits as global foods (user_id=None) so the DB grows over time."""
    foods: list[Food] = []
    for row in rows:
        food = None
        if row.get("barcode"):
            existing = await db.execute(
                select(Food).where(Food.user_id.is_(None), Food.barcode == row["barcode"]).limit(1)
            )
            food = existing.scalar_one_or_none()
        if food is None:
            fields = {k: v for k, v in row.items() if k != "barcode"}
            food = Food(user_id=None, barcode=row.get("barcode") or None, **fields)
            db.add(food)
        foods.append(food)
    try:
        await db.commit()
        for food in foods:
            await db.refresh(food)
    except Exception:
        await db.rollback()
        return []
    return foods


async def search_foods_with_providers(db: AsyncSession, user: User, query: str = "",
                                      limit: int = 20, provider: str = "auto") -> list[Food]:
    """local: DB only. remote: providers only. auto: local first, remote merged in."""
    limit = min(limit, 100)
    if provider == "remote":
        rows = await food_providers.search_remote(query, min(limit, 20))
        return (await _cache_remote_foods(db, rows))[:limit]
    local = await search_foods(db, user, query, limit)
    if provider != "auto" or not query.strip() or len(local) >= limit:
        return local
    rows = await food_providers.search_remote(query, min(limit, 20))
    if not rows:
        return local
    remote = await _cache_remote_foods(db, rows)
    seen = {f.id for f in local}
    return (local + [f for f in remote if f.id not in seen])[:limit]


async def food_by_barcode(db: AsyncSession, user: User, code: str) -> Food | None:
    code = code.strip()
    if not code:
        return None
    result = await db.execute(
        select(Food)
        .where(Food.barcode == code, or_(Food.user_id == user.id, Food.user_id.is_(None)))
        .order_by(Food.user_id.is_(None))
        .limit(1)
    )
    food = result.scalar_one_or_none()
    if food is not None:
        return food
    hit = await food_providers.barcode_remote(code)
    if hit is None:
        return None
    cached = await _cache_remote_foods(db, [hit])
    return cached[0] if cached else None


async def create_food(db: AsyncSession, user: User, data: FoodIn) -> Food:
    food = Food(user_id=user.id, **data.model_dump())
    db.add(food)
    await audit(db, user.id, "food_created", "food", food.id, {"name": food.name})
    await db.commit()
    await db.refresh(food)
    return food


async def update_food(db: AsyncSession, user: User, food_id: UUID, data: FoodIn) -> Food:
    """Only user-owned foods are editable — global reference rows are never mutated."""
    food = await db.get(Food, food_id)
    if food is None or food.user_id != user.id:
        raise HTTPException(404, "Food not found")
    for key, value in data.model_dump().items():
        setattr(food, key, value)
    await db.commit()
    await db.refresh(food)
    return food


async def _resolve_item(db: AsyncSession, user: User, item: dict) -> dict:
    """Compute a nutrient snapshot for one logged item (deterministic)."""
    out = {
        "food_id": str(item["food_id"]) if item.get("food_id") else None,
        "name": item["name"].strip(),
        "quantity": item["quantity"],
        "unit": item.get("unit", "g"),
    }
    food = None
    if item.get("food_id"):
        food = await db.get(Food, item["food_id"])
        if food and food.user_id not in (None, user.id):
            food = None
    exact = True
    if food is None:
        name_l = out["name"].lower().strip()
        singular = name_l.rstrip("s")
        # wide net — the relevance ranker below needs the whole pool, not 8 rows
        matches = await search_foods(db, user, out["name"], limit=50)
        if not matches and singular != name_l:
            matches = await search_foods(db, user, singular, limit=50)
        if not matches:
            # word-reduction: "chicken cutlets" → "chicken"; "rolled oats" → "oats"
            words = [w for w in re.split(r"\s+", name_l) if len(w) > 2]
            subs = [" ".join(words[:n]) for n in range(len(words) - 1, 0, -1)] + \
                   [" ".join(words[n:]) for n in range(1, len(words))]
            for sub in subs:
                matches = await search_foods(db, user, sub, limit=50)
                if matches:
                    break
        exact_match = next(
            (f for f in matches if f.name.lower() in (name_l, singular)
             or f.name.lower().split(" (")[0] in (name_l, singular)),
            None,
        )
        if exact_match is not None:
            food = exact_match
        elif matches:
            # fuzzy: rank by word overlap with the query, then shortest name;
            # "cooked white rice" must land on "White rice (cooked)", never "Chole (cooked)"
            query_words = set(re.split(r"[\s()]+", name_l)) - {"", "cooked", "the", "a"}

            def relevance(f: Food) -> tuple[int, int]:
                food_words = set(re.split(r"[\s()]+", f.name.lower())) - {""}
                overlap = len(query_words & food_words)
                return (-overlap, len(f.name))

            food = min(matches, key=relevance)
            exact = False
    if food is not None:
        out["food_id"] = str(food.id)
        out.update(metrics.scale_nutrients(
            {"serving_size": food.serving_size, "calories": food.calories, "protein": food.protein,
             "carbs": food.carbs, "fat": food.fat, "fiber": food.fiber},
            item["quantity"], item.get("unit", "g"),
        ))
        out["estimated"] = not exact
        if not exact:
            out["confidence"] = 0.6
        # explicitly stated nutrients (user said so, or AI passed them) beat the lookup
        if item.get("calories") is not None:
            for key in ("calories", "protein", "carbs", "fat", "fiber"):
                if item.get(key) is not None:
                    out[key] = float(item[key])
            out["estimated"] = bool(item.get("estimated", True))
            if item.get("confidence") is not None:
                out["confidence"] = item["confidence"]
    elif item.get("calories") is not None:
        # explicit estimate (photo analysis, user knowledge) — keep uncertainty fields
        for key in ("calories", "protein", "carbs", "fat", "fiber"):
            out[key] = float(item.get(key) or 0)
        out["estimated"] = True
        if item.get("confidence") is not None:
            out["confidence"] = item["confidence"]
        if item.get("lower_kcal") is not None:
            out["lower_kcal"] = item["lower_kcal"]
        if item.get("upper_kcal") is not None:
            out["upper_kcal"] = item["upper_kcal"]
    else:
        # Unknown food: explicit zero snapshot, flagged as unverified — never invent numbers.
        out.update({"calories": 0.0, "protein": 0.0, "carbs": 0.0, "fat": 0.0, "fiber": 0.0,
                    "estimated": True, "confidence": 0.0, "unmatched": True})
    return out


async def log_food(db: AsyncSession, user: User, data: FoodLogIn, source: str | None = None) -> FoodLog:
    items = [await _resolve_item(db, user, i.model_dump()) for i in data.items]
    totals = metrics.sum_items(items)
    from datetime import datetime as _dt
    from zoneinfo import ZoneInfo as _ZoneInfo
    _now = _dt.now(_ZoneInfo(user.timezone))
    log = FoodLog(
        user_id=user.id,
        date=parse_date(data.date, user.timezone),
        meal_type=data.meal_type,
        items=items,
        note=data.note,
        source=source or data.source,
        eaten_at=_now,  # defaults to now; user-editable later
        **totals,
    )
    db.add(log)
    await audit(db, user.id, "food_logged", "food_log", log.id,
                {"meal_type": log.meal_type, "calories": log.calories})
    await db.commit()
    await db.refresh(log)
    return log


async def list_food_logs(db: AsyncSession, user: User, day: date | None = None,
                         start: date | None = None, end: date | None = None,
                         limit: int = 50, offset: int = 0, calendar: bool = False) -> list[FoodLog]:
    # calendar=True: raw date-column listing (timeline does its own window math)
    if day is not None and start is None and end is None and not calendar:
        return (await _logs_for_day(db, user, day, limit))[offset:]
    stmt = select(FoodLog).where(FoodLog.user_id == user.id)
    if start:
        stmt = stmt.where(FoodLog.date >= start)
    if end:
        stmt = stmt.where(FoodLog.date <= end)
    result = await db.execute(
        stmt.order_by(FoodLog.date.desc(), FoodLog.created_at.desc()).limit(min(limit, 200)).offset(offset)
    )
    return list(result.scalars().all())


async def delete_food_log(db: AsyncSession, user: User, log_id: UUID) -> None:
    log = await get_owned(db, FoodLog, log_id, user)
    await db.delete(log)
    await audit(db, user.id, "food_log_deleted", "food_log", log_id)
    await db.commit()


async def update_food_log(db: AsyncSession, user: User, log_id: UUID, *,
                          meal_type: str | None = None, note: str | None = None,
                          time: str | None = None,
                          items: list[FoodLogItemIn] | None = None) -> FoodLog:
    """Edit a log: metadata, eaten time, or corrected items.

    When items are provided they replace the log's items and totals are
    recomputed deterministically (explicit per-item nutrients always win over
    the database lookup — user labels beat generic references).
    """
    from datetime import datetime as _dt
    from zoneinfo import ZoneInfo

    log = await get_owned(db, FoodLog, log_id, user)
    if meal_type:
        log.meal_type = meal_type
    if note is not None:
        log.note = note
    if time:
        try:
            h, m = time.split(":")
            tz = ZoneInfo(user.timezone)
            log.eaten_at = _dt(log.date.year, log.date.month, log.date.day, int(h), int(m), tzinfo=tz)
        except (ValueError, AttributeError):
            from fastapi import HTTPException
            raise HTTPException(422, "time must be HH:MM")
    if items is not None:
        resolved = [await _resolve_item(db, user, i.model_dump()) for i in items]
        log.items = resolved
        for key, value in metrics.sum_items(resolved).items():
            setattr(log, key, value)
        await audit(db, user.id, "food_log_corrected", "food_log", log.id,
                    {"calories": log.calories, "items": len(resolved)})
    await db.commit()
    await db.refresh(log)
    return log


async def _effective_dt(log: FoodLog, tz_name: str) -> datetime:
    """When the meal happened: eaten_at when set; legacy rows use created_at (the
    real time of entry — far closer than a noon guess, and lands inside day
    boundaries set in the afternoon)."""
    from datetime import datetime as _dt
    from zoneinfo import ZoneInfo

    ts = log.eaten_at or log.created_at
    if ts is not None:
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    return _dt(log.date.year, log.date.month, log.date.day, 12, 0, tzinfo=ZoneInfo(tz_name))


async def _logs_for_day(db: AsyncSession, user: User, day: date, limit: int = 200) -> list[FoodLog]:
    """Logs belonging to `day` — calendar date, or the user's custom day window."""
    boundary = await day_start_minutes(db, user)
    win = day_window(day, user.timezone, boundary)
    if win is None:
        result = await db.execute(
            select(FoodLog).where(FoodLog.user_id == user.id, FoodLog.date == day)
            .order_by(FoodLog.created_at.desc()).limit(limit)
        )
        return list(result.scalars().all())
    start, end = win
    start_utc = start.astimezone(timezone.utc)
    end_utc = end.astimezone(timezone.utc)
    result = await db.execute(
        select(FoodLog).where(FoodLog.user_id == user.id, FoodLog.date.in_([day, day + timedelta(days=1)]))
        .order_by(FoodLog.created_at.desc()).limit(limit)
    )
    out = []
    for log in result.scalars().all():
        ts = await _effective_dt(log, user.timezone)
        if start_utc <= ts < end_utc:
            out.append(log)
    return out


async def daily_totals(db: AsyncSession, user: User, day: date) -> dict:
    logs = await _logs_for_day(db, user, day)
    cal = sum(l.calories for l in logs)
    pro = sum(l.protein for l in logs)
    carb = sum(l.carbs for l in logs)
    fat = sum(l.fat for l in logs)
    fiber = sum(l.fiber for l in logs)
    return {"date": day, "calories": round(cal, 1), "protein": round(pro, 1),
            "carbs": round(carb, 1), "fat": round(fat, 1), "fiber": round(fiber, 1)}


async def nutrition_history(db: AsyncSession, user: User, start: date, end: date) -> list[dict]:
    result = await db.execute(
        select(FoodLog.date, func.sum(FoodLog.calories), func.sum(FoodLog.protein))
        .where(FoodLog.user_id == user.id, FoodLog.date >= start, FoodLog.date <= end)
        .group_by(FoodLog.date)
        .order_by(FoodLog.date)
    )
    return [{"date": d, "calories": round(c or 0, 1), "protein": round(p or 0, 1)} for d, c, p in result.all()]
