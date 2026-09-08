from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import AuditLog, User


async def audit(db: AsyncSession, user_id: UUID, event: str, entity_type: str | None = None,
                entity_id: Any = None, data: dict | None = None) -> None:
    db.add(AuditLog(user_id=user_id, event=event, entity_type=entity_type,
                    entity_id=str(entity_id) if entity_id is not None else None, data=data or {}))


def owned(stmt: Select, model: Any, user: User):
    return stmt.where(model.user_id == user.id)


async def get_owned(db: AsyncSession, model: Any, obj_id: UUID, user: User):
    obj = await db.get(model, obj_id)
    if obj is None or getattr(obj, "user_id", None) != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"{model.__name__} not found")
    return obj


async def list_owned(db: AsyncSession, model: Any, user: User, limit: int = 100, offset: int = 0):
    result = await db.execute(
        select(model).where(model.user_id == user.id).limit(min(limit, 500)).offset(offset)
    )
    return list(result.scalars().all())
