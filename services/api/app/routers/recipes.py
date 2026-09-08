from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..deps import current_user
from ..models import User
from ..schemas import MealPlanIn, MealPlanOut, RecipeIn, RecipeOut
from ..services import recipes as recipes_service

router = APIRouter(tags=["recipes"])


@router.get("/recipes", response_model=list[RecipeOut])
async def list_recipes(q: str = "", user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    return await recipes_service.list_recipes(db, user, q)


@router.post("/recipes", response_model=RecipeOut, status_code=201)
async def create_recipe(data: RecipeIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    return await recipes_service.create_recipe(db, user, data)


@router.get("/recipes/{recipe_id}", response_model=RecipeOut)
async def get_recipe(recipe_id: UUID, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    return await recipes_service.get_recipe(db, user, recipe_id)


@router.put("/recipes/{recipe_id}", response_model=RecipeOut)
async def update_recipe(recipe_id: UUID, data: RecipeIn, user: User = Depends(current_user),
                        db: AsyncSession = Depends(get_db)):
    return await recipes_service.update_recipe(db, user, recipe_id, data)


@router.delete("/recipes/{recipe_id}", status_code=204)
async def delete_recipe(recipe_id: UUID, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    await recipes_service.delete_recipe(db, user, recipe_id)
    return None


@router.get("/recipes/{recipe_id}/nutrition")
async def recipe_nutrition(recipe_id: UUID, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    return await recipes_service.recipe_nutrition(db, user, recipe_id)


@router.get("/meal-plans", response_model=list[MealPlanOut])
async def list_meal_plans(start: date, end: date, user: User = Depends(current_user),
                          db: AsyncSession = Depends(get_db)):
    return await recipes_service.list_meal_plans(db, user, start, end)


@router.post("/meal-plans", response_model=MealPlanOut, status_code=201)
async def create_meal_plan(data: MealPlanIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    return await recipes_service.create_meal_plan(db, user, data)


@router.delete("/meal-plans/{plan_id}", status_code=204)
async def delete_meal_plan(plan_id: UUID, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    await recipes_service.delete_meal_plan(db, user, plan_id)
    return None


@router.get("/grocery-list")
async def grocery_list(start: date, end: date, user: User = Depends(current_user),
                       db: AsyncSession = Depends(get_db)):
    return {"items": await recipes_service.grocery_list(db, user, start, end)}
