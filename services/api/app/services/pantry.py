"""Track D — pantry inventory, recipe matching, grocery-list purchase upsert."""

from datetime import date
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import PantryItem, User
from ..schemas import PantryItemIn, PantryItemPatch
from . import recipes as recipes_service
from .common import audit, get_owned


async def list_items(db: AsyncSession, user: User) -> list[PantryItem]:
    result = await db.execute(
        select(PantryItem).where(PantryItem.user_id == user.id)
        .order_by(PantryItem.location, PantryItem.name)
    )
    return list(result.scalars().all())


async def create_item(db: AsyncSession, user: User, data: PantryItemIn) -> PantryItem:
    item = PantryItem(user_id=user.id, **data.model_dump())
    item.name = item.name.strip()
    item.location = (item.location or "pantry").strip().lower()
    db.add(item)
    await audit(db, user.id, "pantry_item_added", "pantry_item", item.id, {"name": item.name})
    await db.commit()
    await db.refresh(item)
    return item


async def update_item(db: AsyncSession, user: User, item_id: UUID, patch: PantryItemPatch) -> PantryItem:
    item = await get_owned(db, PantryItem, item_id, user)
    for key, value in patch.model_dump(exclude_unset=True).items():
        if isinstance(value, str):
            value = value.strip().lower() if key == "location" else value.strip()
        setattr(item, key, value)
    await db.commit()
    await db.refresh(item)
    return item


async def delete_item(db: AsyncSession, user: User, item_id: UUID) -> None:
    item = await get_owned(db, PantryItem, item_id, user)
    await db.delete(item)
    await db.commit()


# ---------- recipe matches ----------

def _norm(name: str) -> str:
    return " ".join(name.strip().lower().split())


def _covered(ingredient: str, pantry_names: list[str]) -> bool:
    """Case-insensitive substring match, either direction ('rice' covers 'rice vinegar')."""
    n = _norm(ingredient)
    return any(p in n or n in p for p in pantry_names)


async def recipe_matches(db: AsyncSession, user: User) -> list[dict]:
    items = await list_items(db, user)
    pantry_names = [_norm(i.name) for i in items if i.name.strip()]
    if not pantry_names:
        return []
    recipes = await recipes_service.list_recipes(db, user, limit=200)
    out: list[dict] = []
    for recipe in recipes:
        names = [str(i.get("name", "")).strip() for i in recipe.ingredients or []]
        names = [n for n in names if n]
        if not names:
            continue
        missing = [n for n in names if not _covered(n, pantry_names)]
        coverage = round((len(names) - len(missing)) / len(names), 3)
        if coverage > 0:
            out.append({"recipe_id": recipe.id, "name": recipe.name,
                        "coverage": coverage, "missing": missing})
    out.sort(key=lambda r: (-r["coverage"], r["name"].lower()))
    return out


# ---------- grocery purchase ----------

async def purchase_groceries(db: AsyncSession, user: User, start: date, end: date) -> dict:
    """Upsert the grocery list for [start, end] into the pantry, keyed by
    (lowercased name, unit) — quantities accumulate, rows never duplicate."""
    groceries = await recipes_service.grocery_list(db, user, start, end)
    added = 0
    for entry in groceries:
        name = entry["name"].strip()
        unit = entry["unit"]
        qty = float(entry["quantity"] or 0)
        if not name:
            continue
        existing = await db.execute(
            select(PantryItem).where(
                PantryItem.user_id == user.id,
                func.lower(PantryItem.name) == name.lower(),
                PantryItem.unit == unit,
            ).limit(1)
        )
        item = existing.scalar_one_or_none()
        if item is None:
            db.add(PantryItem(user_id=user.id, name=name, quantity=qty, unit=unit))
        else:
            item.quantity = round(item.quantity + qty, 1)
        added += 1
    await audit(db, user.id, "grocery_purchased", "pantry_item", None,
                {"added": added, "start": str(start), "end": str(end)})
    await db.commit()
    return {"added": added}
