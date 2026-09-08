from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import User, UserPreference, UserProfile
from ..schemas import SignupIn
from ..security import hash_password, verify_password


async def signup(db: AsyncSession, data: SignupIn) -> User:
    existing = await db.execute(select(User).where(User.email == data.email.lower()))
    if existing.scalar_one_or_none():
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Email already registered")
    user = User(email=data.email.lower(), password_hash=hash_password(data.password), name=data.name.strip())
    db.add(user)
    await db.flush()
    db.add(UserProfile(user_id=user.id))
    db.add(UserPreference(user_id=user.id, data={}))
    await db.commit()
    await db.refresh(user)
    return user


async def authenticate(db: AsyncSession, email: str, password: str) -> User | None:
    result = await db.execute(select(User).where(User.email == email.lower()))
    user = result.scalar_one_or_none()
    if user is None or not verify_password(password, user.password_hash):
        return None
    return user
