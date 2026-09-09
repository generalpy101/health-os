"""Track D — saved meals (re-loggable item bundles) and frequent foods."""

import uuid
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Food, FoodLog, SavedMeal, User
from ..schemas import FoodLogIn, FoodLogItemIn, SavedMealIn, SavedMealLogIn
from ..utils.time import user_today
from . import nutrition as nutrition_service
from .common import audit, get_owned
from .nutrition import _resolve_item


async def list_saved_meals(db: AsyncSession, user: User) -> list[SavedMeal]:
    result = await db.execute(
        select(SavedMeal).where(SavedMeal.user_id == user.id)
        .order_by(SavedMeal.use_count.desc(), SavedMeal.name)
    )
    return list(result.scalars().all())


async def create_saved_meal(db: AsyncSession, user: User, data: SavedMealIn) -> SavedMeal:
    if data.from_log_id is not None:
        log = await get_owned(db, FoodLog, data.from_log_id, user)
        items = [dict(i) for i in log.items or []]  # already resolved snapshots
    elif data.items:
        items = [await _resolve_item(db, user, i.model_dump()) for i in data.items]
    else:
        raise HTTPException(422, "Provide items or from_log_id")
    if not items:
        raise HTTPException(422, "A saved meal needs at least one item")
    meal = SavedMeal(user_id=user.id, name=data.name.strip(), items=items)
    db.add(meal)
    await audit(db, user.id, "saved_meal_created", "saved_meal", meal.id, {"name": meal.name})
    await db.commit()
    await db.refresh(meal)
    return meal


def _item_in(stored: dict) -> FoodLogItemIn:
    """Rebuild a loggable item from a snapshot. Linked foods re-resolve fresh from the
    food row; unlinked items keep their explicit (estimated/unmatched) numbers."""
    base: dict = {
        "food_id": stored.get("food_id"),
        "name": stored.get("name") or "?",
        "quantity": stored.get("quantity") or 1,
        "unit": stored.get("unit", "g"),
    }
    if not stored.get("food_id"):
        for key in ("calories", "protein", "carbs", "fat", "fiber", "confidence"):
            if stored.get(key) is not None:
                base[key] = stored[key]
        base["estimated"] = True
    return FoodLogItemIn(**base)


async def log_saved_meal(db: AsyncSession, user: User, meal_id: UUID, data: SavedMealLogIn) -> FoodLog:
    meal = await get_owned(db, SavedMeal, meal_id, user)
    if not meal.items:
        raise HTTPException(422, "Saved meal has no items")
    log_in = FoodLogIn(date=data.date, meal_type=data.meal_type,
                       items=[_item_in(i) for i in meal.items])
    log = await nutrition_service.log_food(db, user, log_in, source="saved_meal")
    meal.use_count += 1
    meal.last_used_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(log)
    return log


async def delete_saved_meal(db: AsyncSession, user: User, meal_id: UUID) -> None:
    meal = await get_owned(db, SavedMeal, meal_id, user)
    await db.delete(meal)
    await audit(db, user.id, "saved_meal_deleted", "saved_meal", meal_id)
    await db.commit()


# ---------- frequent foods ----------

async def frequent_foods(db: AsyncSession, user: User, limit: int = 12) -> list[dict]:
    """Most-logged items over the last 60 days, keyed by food_id or lowercased name.
    Calories/protein come from the linked food (per serving) or the latest snapshot."""
    start = user_today(user.timezone) - timedelta(days=59)
    result = await db.execute(
        select(FoodLog).where(FoodLog.user_id == user.id, FoodLog.date >= start)
        .order_by(FoodLog.date.asc(), FoodLog.created_at.asc())
    )
    agg: dict[tuple[str, str], dict] = {}
    for log in result.scalars().all():
        for item in log.items or []:
            fid = item.get("food_id")
            name = (item.get("name") or "").strip()
            if not fid and not name:
                continue
            key = ("id", str(fid)) if fid else ("name", name.lower())
            entry = agg.setdefault(key, {"uses": 0, "name": name, "snap": {}})
            entry["uses"] += 1
            if name:
                entry["name"] = name
            entry["snap"] = item  # ascending iteration -> latest snapshot wins

    ids: list[uuid.UUID] = []
    for kind, raw in agg:
        if kind == "id":
            try:
                ids.append(uuid.UUID(raw))
            except ValueError:
                pass
    foods: dict[str, Food] = {}
    if ids:
        rows = await db.execute(select(Food).where(Food.id.in_(ids)))
        foods = {str(f.id): f for f in rows.scalars().all()}

    out: list[dict] = []
    for (kind, raw), entry in agg.items():
        food = foods.get(raw) if kind == "id" else None
        if food is not None:
            calories, protein, name, food_id = food.calories, food.protein, food.name, food.id
        else:
            snap = entry["snap"]
            calories = float(snap.get("calories") or 0)
            protein = float(snap.get("protein") or 0)
            name, food_id = entry["name"], None
        out.append({"food_id": food_id, "name": name, "calories": round(calories, 1),
                    "protein": round(protein, 1), "uses": entry["uses"]})
    out.sort(key=lambda r: (-r["uses"], r["name"].lower()))
    return out[: min(limit, 50)]
