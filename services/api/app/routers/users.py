from fastapi import APIRouter, Depends
from sqlalchemy import select
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
