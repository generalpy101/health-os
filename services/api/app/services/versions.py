"""Plan versioning (Track C).

Services hook `record_version` BEFORE mutating a row; the snapshot is the full
pre-change row as JSON. Revert writes the snapshot back through the normal
service path (so audit + a new "revert to vN" version row are produced by the
hook itself) — reverting a revert is therefore possible.
"""

import uuid
from datetime import date, datetime
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, inspect, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Goal, PlanVersion, Target, User, WorkoutPlan

VERSIONED_MODELS: dict[str, type] = {"goal": Goal, "target": Target, "workout_plan": WorkoutPlan}


def row_snapshot(obj: Any) -> dict:
    """Full row as a JSON-safe dict (dates/UUIDs as ISO strings)."""
    out: dict = {}
    for col in inspect(type(obj)).mapper.column_attrs:
        value = getattr(obj, col.key)
        if isinstance(value, (datetime, date)):
            value = value.isoformat()
        elif isinstance(value, uuid.UUID):
            value = str(value)
        out[col.key] = value
    return out


async def record_version(db: AsyncSession, user_id: UUID, entity_type: str, entity_id: Any,
                         snapshot: dict, reason: str, actor: str = "user") -> PlanVersion:
    """Append a version row (call BEFORE mutating the entity). No commit — the
    caller's service commits everything in one transaction."""
    result = await db.execute(
        select(func.coalesce(func.max(PlanVersion.version), 0)).where(
            PlanVersion.user_id == user_id,
            PlanVersion.entity_type == entity_type,
            PlanVersion.entity_id == str(entity_id),
        )
    )
    version = PlanVersion(
        user_id=user_id, entity_type=entity_type, entity_id=str(entity_id),
        version=result.scalar_one() + 1, snapshot=snapshot, reason=reason, actor=actor,
    )
    db.add(version)
    return version


async def list_versions(db: AsyncSession, user: User, entity_type: str | None = None,
                        entity_id: str | None = None, limit: int = 50) -> list[PlanVersion]:
    stmt = select(PlanVersion).where(PlanVersion.user_id == user.id)
    if entity_type:
        stmt = stmt.where(PlanVersion.entity_type == entity_type)
    if entity_id:
        stmt = stmt.where(PlanVersion.entity_id == entity_id)
    result = await db.execute(stmt.order_by(PlanVersion.created_at.desc()).limit(min(limit, 200)))
    return list(result.scalars().all())


async def revert_version(db: AsyncSession, user: User, version_id: UUID) -> Any:
    """Write a version's snapshot back via the entity's normal update service."""
    from ..schemas import GoalPatch, TargetPatch, WorkoutPlanIn
    from . import fitness, goals

    pv = await db.get(PlanVersion, version_id)
    if pv is None or pv.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Version not found")
    model = VERSIONED_MODELS.get(pv.entity_type)
    if model is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Cannot revert {pv.entity_type}")
    try:
        entity_pk = uuid.UUID(pv.entity_id)
    except ValueError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Bad entity id in version")
    entity = await db.get(model, entity_pk)
    if entity is None or entity.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"{pv.entity_type} no longer exists")

    reason = f"revert to v{pv.version}"
    snap = pv.snapshot
    # Only fields accepted by the entity's normal input schema are restored
    # (e.g. GoalPatch has no start_date; immutable columns are never touched).
    if pv.entity_type == "goal":
        patch = GoalPatch(**{k: v for k, v in snap.items() if k in GoalPatch.model_fields})
        return await goals.update_goal(db, user, entity.id, patch, reason=reason)
    if pv.entity_type == "target":
        patch = TargetPatch(**{k: v for k, v in snap.items() if k in TargetPatch.model_fields})
        return await goals.update_target(db, user, entity.id, patch, reason=reason)
    plan_in = WorkoutPlanIn(**{k: v for k, v in snap.items() if k in WorkoutPlanIn.model_fields})
    return await fitness.update_plan(db, user, entity.id, plan_in, reason=reason)
