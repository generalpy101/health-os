from datetime import date
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Food, FoodLog, User
from ..schemas import FoodIn, FoodLogIn
from ..utils import metrics
from ..utils.time import parse_date
from .common import audit, get_owned


async def search_foods(db: AsyncSession, user: User, query: str = "", limit: int = 20) -> list[Food]:
    stmt = select(Food).where(or_(Food.user_id == user.id, Food.user_id.is_(None)))
    if query:
        stmt = stmt.where(Food.name.ilike(f"%{query}%"))
    stmt = stmt.order_by(Food.user_id.is_(None), Food.name).limit(min(limit, 100))
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def create_food(db: AsyncSession, user: User, data: FoodIn) -> Food:
    food = Food(user_id=user.id, **data.model_dump())
    db.add(food)
    await audit(db, user.id, "food_created", "food", food.id, {"name": food.name})
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
        matches = await search_foods(db, user, out["name"], limit=8)
        if not matches and singular != name_l:
            matches = await search_foods(db, user, singular, limit=8)
        exact_match = next(
            (f for f in matches if f.name.lower() in (name_l, singular)
             or f.name.lower().split(" (")[0] in (name_l, singular)),
            None,
        )
        if exact_match is not None:
            food = exact_match
        elif matches:
            # fuzzy: prefer the shortest (most generic) match, flagged as an estimate
            food = min(matches, key=lambda f: len(f.name))
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
    else:
        # Unknown food: explicit zero snapshot, flagged as unverified — never invent numbers.
        out.update({"calories": 0.0, "protein": 0.0, "carbs": 0.0, "fat": 0.0, "fiber": 0.0,
                    "estimated": True, "confidence": 0.0, "unmatched": True})
    return out


async def log_food(db: AsyncSession, user: User, data: FoodLogIn, source: str | None = None) -> FoodLog:
    items = [await _resolve_item(db, user, i.model_dump()) for i in data.items]
    totals = metrics.sum_items(items)
    log = FoodLog(
        user_id=user.id,
        date=parse_date(data.date, user.timezone),
        meal_type=data.meal_type,
        items=items,
        note=data.note,
        source=source or data.source,
        **totals,
    )
    db.add(log)
    await audit(db, user.id, "food_logged", "food_log", log.id,
                {"meal_type": log.meal_type, "calories": log.calories})
    await db.commit()
    await db.refresh(log)
    return log


async def list_food_logs(db: AsyncSession, user: User, day: date | None = None,
                         limit: int = 50, offset: int = 0) -> list[FoodLog]:
    stmt = select(FoodLog).where(FoodLog.user_id == user.id)
    if day:
        stmt = stmt.where(FoodLog.date == day)
    stmt = stmt.order_by(FoodLog.date.desc(), FoodLog.created_at.desc()).limit(min(limit, 200)).offset(offset)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def delete_food_log(db: AsyncSession, user: User, log_id: UUID) -> None:
    log = await get_owned(db, FoodLog, log_id, user)
    await db.delete(log)
    await audit(db, user.id, "food_log_deleted", "food_log", log_id)
    await db.commit()


async def daily_totals(db: AsyncSession, user: User, day: date) -> dict:
    result = await db.execute(
        select(
            func.coalesce(func.sum(FoodLog.calories), 0),
            func.coalesce(func.sum(FoodLog.protein), 0),
            func.coalesce(func.sum(FoodLog.carbs), 0),
            func.coalesce(func.sum(FoodLog.fat), 0),
            func.coalesce(func.sum(FoodLog.fiber), 0),
        ).where(FoodLog.user_id == user.id, FoodLog.date == day)
    )
    cal, pro, carb, fat, fiber = result.one()
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
