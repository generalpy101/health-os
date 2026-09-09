"""Track D — pantry inventory, recipe matching, grocery purchase."""

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..deps import current_user
from ..models import User
from ..schemas import (GroceryPurchaseIn, PantryItemIn, PantryItemOut, PantryItemPatch,
                       RecipeMatchOut)
from ..services import pantry as pantry_service

router = APIRouter(tags=["pantry"])


@router.get("/pantry", response_model=list[PantryItemOut])
async def list_pantry(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    return await pantry_service.list_items(db, user)


@router.post("/pantry", response_model=PantryItemOut, status_code=201)
async def create_pantry_item(data: PantryItemIn, user: User = Depends(current_user),
                             db: AsyncSession = Depends(get_db)):
    return await pantry_service.create_item(db, user, data)


@router.get("/pantry/recipe-matches", response_model=list[RecipeMatchOut])
async def recipe_matches(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    return await pantry_service.recipe_matches(db, user)


@router.patch("/pantry/{item_id}", response_model=PantryItemOut)
async def update_pantry_item(item_id: UUID, data: PantryItemPatch, user: User = Depends(current_user),
                             db: AsyncSession = Depends(get_db)):
    return await pantry_service.update_item(db, user, item_id, data)


@router.delete("/pantry/{item_id}", status_code=204)
async def delete_pantry_item(item_id: UUID, user: User = Depends(current_user),
                             db: AsyncSession = Depends(get_db)):
    await pantry_service.delete_item(db, user, item_id)
    return None


@router.post("/grocery-list/purchase")
async def purchase_groceries(data: GroceryPurchaseIn, user: User = Depends(current_user),
                             db: AsyncSession = Depends(get_db)):
    return await pantry_service.purchase_groceries(db, user, data.start, data.end)
