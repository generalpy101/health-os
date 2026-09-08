from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..deps import current_user
from ..models import User, UserMemory, UserPreference, UserProfile
from ..schemas import PreferencesIn, ProfileIn, ProfileOut, UserOut, UserPatch

router = APIRouter(tags=["users"])


@router.get("/users/me", response_model=UserOut)
async def get_me(user: User = Depends(current_user)):
    return user


@router.patch("/users/me", response_model=UserOut)
async def patch_me(patch: UserPatch, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    for key, value in patch.model_dump(exclude_none=True).items():
        setattr(user, key, value)
    await db.commit()
    await db.refresh(user)
    return user


@router.get("/users/me/profile", response_model=ProfileOut)
async def get_profile(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    profile = (await db.execute(select(UserProfile).where(UserProfile.user_id == user.id))).scalar_one_or_none()
    if profile is None:
        profile = UserProfile(user_id=user.id)
        db.add(profile)
        await db.commit()
        await db.refresh(profile)
    return profile


@router.put("/users/me/profile", response_model=ProfileOut)
async def put_profile(data: ProfileIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    profile = (await db.execute(select(UserProfile).where(UserProfile.user_id == user.id))).scalar_one_or_none()
    if profile is None:
        profile = UserProfile(user_id=user.id)
        db.add(profile)
        await db.flush()
    for key, value in data.model_dump(exclude_none=True).items():
        setattr(profile, key, value)
    await db.commit()
    await db.refresh(profile)
    return profile


@router.get("/users/me/preferences")
async def get_preferences(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    pref = (await db.execute(select(UserPreference).where(UserPreference.user_id == user.id))).scalar_one_or_none()
    return {"data": pref.data if pref else {}}


@router.put("/users/me/preferences")
async def put_preferences(body: PreferencesIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    pref = (await db.execute(select(UserPreference).where(UserPreference.user_id == user.id))).scalar_one_or_none()
    if pref is None:
        pref = UserPreference(user_id=user.id, data={})
        db.add(pref)
        await db.flush()
    pref.data = {**pref.data, **body.data}  # shallow merge so clients can patch sections
    await db.commit()
    return {"data": pref.data}


@router.get("/users/me/export")
async def export_data(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    """Full structured export of the user's data (JSON)."""
    from .. import models
    from ..services.common import list_owned

    out: dict = {"user": {"email": user.email, "name": user.name, "timezone": user.timezone,
                          "units": user.units, "exported_at": __import__("datetime").datetime.now(
                              __import__("datetime").timezone.utc).isoformat()}}

    table_fields = {
        "Goal": ["type", "title", "status", "priority", "start_value", "target_value", "unit",
                 "start_date", "target_date", "created_at"],
        "Target": ["key", "value", "unit", "period", "mode", "source", "active"],
        "FoodLog": ["date", "meal_type", "items", "calories", "protein", "carbs", "fat", "fiber", "source"],
        "Recipe": ["name", "description", "servings", "ingredients", "steps", "nutrition", "tags", "cuisine"],
        "MealPlan": ["date", "meal_type", "name", "servings", "notes"],
        "WorkoutSession": ["date", "title", "duration_min", "exercises", "total_volume", "notes"],
        "Activity": ["type", "date", "duration_min", "distance_m", "steps", "calories_est", "notes"],
        "SleepLog": ["date", "sleep_start", "sleep_end", "duration_min", "quality", "notes"],
        "WaterLog": ["date", "amount_ml"],
        "Measurement": ["type", "value", "unit", "date", "source", "notes"],
        "Habit": ["name", "frequency", "target", "unit", "active"],
        "HabitLog": ["habit_id", "date", "status", "value", "notes"],
        "ScheduleEvent": ["type", "title", "start_at", "end_at", "recurrence", "status"],
        "UserMemory": ["type", "key", "value", "source", "confidence", "status"],
        "AIConversation": ["title", "created_at"],
    }
    all_rows: dict[str, list] = {}
    for name in table_fields:
        model = getattr(models, name)
        all_rows[name] = await list_owned(db, model, user, limit=100000)

    from datetime import date, datetime

    def safe(v):
        if isinstance(v, (datetime, date)):
            return v.isoformat()
        if hasattr(v, "hex") and not isinstance(v, str) and not isinstance(v, float):
            return str(v)
        return v

    export = {name.lower() + "s": [
        {f: safe(getattr(r, f, None)) for f in fields} for r in rows
    ] for name, fields in table_fields.items() for rows in [all_rows[name]]}

    profile = (await db.execute(select(UserProfile).where(UserProfile.user_id == user.id))).scalar_one_or_none()
    if profile:
        out["profile"] = {"height_cm": profile.height_cm, "birth_year": profile.birth_year,
                          "sex": profile.sex, "activity_level": profile.activity_level,
                          "dietary": profile.dietary}
    out.update(export)
    return JSONResponse(out, headers={"Content-Disposition": 'attachment; filename="healthos-export.json"'})


@router.delete("/users/me", status_code=204)
async def delete_account(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    """Hard-delete the account and all owned data (photos included)."""
    from .. import models
    from ..storage import delete_photo

    owned_models = [
        models.AIMessage, models.AIAction, models.AIConversation, models.AuditLog,
        models.Recommendation, models.UserMemory, models.UserPreference, models.ScheduleEvent,
        models.HabitLog, models.Habit, models.Measurement, models.WaterLog, models.SleepLog,
        models.Activity, models.WorkoutSession, models.WorkoutPlan, models.MealPlan,
        models.Recipe, models.FoodLog, models.Food, models.Target, models.Goal,
        models.Photo, models.Session, models.UserProfile,
    ]
    photos = (await db.execute(select(models.Photo).where(models.Photo.user_id == user.id))).scalars().all()
    for p in photos:
        delete_photo(p.storage_key)
    for model in owned_models:
        await db.execute(delete(model).where(model.user_id == user.id))
    await db.delete(user)
    await db.commit()
    return None


@router.get("/users/me/memories")
async def list_memories(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(UserMemory).where(UserMemory.user_id == user.id).order_by(UserMemory.updated_at.desc()).limit(200)
    )
    return [{"id": str(m.id), "type": m.type, "key": m.key, "value": m.value, "source": m.source,
             "confidence": m.confidence, "status": m.status} for m in result.scalars().all()]


@router.delete("/users/me/memories/{memory_id}", status_code=204)
async def delete_memory(memory_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(UserMemory).where(UserMemory.user_id == user.id, UserMemory.id == memory_id)
    )
    mem = result.scalar_one_or_none()
    if mem:
        await db.delete(mem)
        await db.commit()
    return None
