from collections import defaultdict
from datetime import date
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import MealPlan, Recipe, User
from ..schemas import MealPlanIn, RecipeIn
from ..utils import metrics
from .common import audit, get_owned
from .nutrition import _resolve_item


async def create_recipe(db: AsyncSession, user: User, data: RecipeIn, source: str = "user") -> Recipe:
    ingredients = [await _resolve_item(db, user, i.model_dump()) for i in data.ingredients]
    nutrition = metrics.recipe_nutrition_per_serving(ingredients, data.servings)
    recipe = Recipe(
        user_id=user.id, name=data.name, description=data.description, servings=data.servings,
        prep_minutes=data.prep_minutes, cook_minutes=data.cook_minutes, ingredients=ingredients,
        steps=data.steps, nutrition=nutrition, tags=data.tags, cuisine=data.cuisine,
        difficulty=data.difficulty, source=source,
    )
    db.add(recipe)
    await audit(db, user.id, "recipe_created", "recipe", recipe.id, {"name": recipe.name, "source": source})
    await db.commit()
    await db.refresh(recipe)
    return recipe


async def list_recipes(db: AsyncSession, user: User, query: str = "", limit: int = 50, offset: int = 0) -> list[Recipe]:
    stmt = select(Recipe).where(Recipe.user_id == user.id)
    if query:
        stmt = stmt.where(or_(Recipe.name.ilike(f"%{query}%"), Recipe.cuisine.ilike(f"%{query}%")))
    result = await db.execute(stmt.order_by(Recipe.created_at.desc()).limit(min(limit, 200)).offset(offset))
    return list(result.scalars().all())


async def get_recipe(db: AsyncSession, user: User, recipe_id: UUID) -> Recipe:
    return await get_owned(db, Recipe, recipe_id, user)


async def update_recipe(db: AsyncSession, user: User, recipe_id: UUID, data: RecipeIn) -> Recipe:
    recipe = await get_owned(db, Recipe, recipe_id, user)
    ingredients = [await _resolve_item(db, user, i.model_dump()) for i in data.ingredients]
    recipe.name = data.name
    recipe.description = data.description
    recipe.servings = data.servings
    recipe.prep_minutes = data.prep_minutes
    recipe.cook_minutes = data.cook_minutes
    recipe.ingredients = ingredients
    recipe.steps = data.steps
    recipe.nutrition = metrics.recipe_nutrition_per_serving(ingredients, data.servings)
    recipe.tags = data.tags
    recipe.cuisine = data.cuisine
    recipe.difficulty = data.difficulty
    await audit(db, user.id, "recipe_updated", "recipe", recipe.id, {"name": recipe.name})
    await db.commit()
    await db.refresh(recipe)
    return recipe


async def delete_recipe(db: AsyncSession, user: User, recipe_id: UUID) -> None:
    recipe = await get_owned(db, Recipe, recipe_id, user)
    await db.delete(recipe)
    await audit(db, user.id, "recipe_deleted", "recipe", recipe_id)
    await db.commit()


async def recipe_nutrition(db: AsyncSession, user: User, recipe_id: UUID) -> dict:
    recipe = await get_owned(db, Recipe, recipe_id, user)
    return metrics.recipe_nutrition_per_serving(recipe.ingredients, recipe.servings)


# ---------- meal plans ----------

async def create_meal_plan(db: AsyncSession, user: User, data: MealPlanIn) -> MealPlan:
    fields = data.model_dump()
    time_str = fields.pop("time", None)
    time_minutes = None
    if time_str:
        try:
            h, m = time_str.split(":")
            time_minutes = int(h) * 60 + int(m)
            if not (0 <= time_minutes < 24 * 60):
                time_minutes = None
        except (ValueError, AttributeError):
            time_minutes = None
    plan = MealPlan(user_id=user.id, time_minutes=time_minutes, **fields)
    db.add(plan)
    await db.commit()
    await db.refresh(plan)
    return plan


async def list_meal_plans(db: AsyncSession, user: User, start: date, end: date) -> list[MealPlan]:
    result = await db.execute(
        select(MealPlan).where(MealPlan.user_id == user.id, MealPlan.date >= start, MealPlan.date <= end)
        .order_by(MealPlan.date)
    )
    return list(result.scalars().all())


async def delete_meal_plan(db: AsyncSession, user: User, plan_id: UUID) -> None:
    plan = await get_owned(db, MealPlan, plan_id, user)
    await db.delete(plan)
    await db.commit()


async def grocery_list(db: AsyncSession, user: User, start: date, end: date) -> list[dict]:
    """Consolidate ingredients across planned meals in a date range (deterministic)."""
    plans = await list_meal_plans(db, user, start, end)
    totals: dict[tuple[str, str], float] = defaultdict(float)
    for plan in plans:
        if plan.recipe_id is None:
            continue
        recipe = await db.get(Recipe, plan.recipe_id)
        if recipe is None or recipe.user_id != user.id or not recipe.servings:
            continue
        scale = (plan.servings or 1) / recipe.servings
        for ing in recipe.ingredients:
            key = (ing.get("name", "?").strip().lower(), ing.get("unit", "g"))
            totals[key] += float(ing.get("quantity") or 0) * scale
    return [
        {"name": name, "quantity": round(qty, 1), "unit": unit}
        for (name, unit), qty in sorted(totals.items())
    ]
