import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import get_settings
from .models import Session, User


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:
        return False


def _token_id(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def create_session(db: AsyncSession, user: User) -> str:
    settings = get_settings()
    token = secrets.token_urlsafe(32)
    session = Session(
        id=_token_id(token),
        user_id=user.id,
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.session_ttl_days),
    )
    db.add(session)
    await db.commit()
    return token


async def get_user_for_token(db: AsyncSession, token: str | None) -> User | None:
    if not token:
        return None
    result = await db.execute(select(Session).where(Session.id == _token_id(token)))
    session = result.scalar_one_or_none()
    if session is None:
        return None
    expires = session.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires < datetime.now(timezone.utc):
        await db.delete(session)
        await db.commit()
        return None
    return await db.get(User, session.user_id)


async def delete_session(db: AsyncSession, token: str | None) -> None:
    if not token:
        return
    await db.execute(delete(Session).where(Session.id == _token_id(token)))
    await db.commit()
