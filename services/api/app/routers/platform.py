"""Track C — platform depth: plan versioning, device integrations, search."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..deps import current_user
from ..models import User
from ..schemas import IngestIn
from ..services import devices, search as search_service
from ..services import versions as versions_service
from ..services.versions import row_snapshot

router = APIRouter(tags=["platform"])


# ---------- plan versions ----------

def _version_out(v) -> dict:
    return {"id": str(v.id), "version": v.version, "snapshot": v.snapshot,
            "reason": v.reason, "actor": v.actor, "created_at": v.created_at.isoformat()}


@router.get("/versions/{entity_type}/{entity_id}")
async def list_entity_versions(entity_type: str, entity_id: str,
                               user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    if entity_type not in versions_service.VERSIONED_MODELS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Unknown entity type {entity_type!r}")
    rows = await versions_service.list_versions(db, user, entity_type, entity_id)
    return [_version_out(v) for v in rows]


@router.get("/versions")
async def recent_versions(limit: int = Query(default=20, le=100),
                          user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    """Recent versions across all entities (settings "Plan history" card)."""
    rows = await versions_service.list_versions(db, user, limit=limit)
    return [{**_version_out(v), "entity_type": v.entity_type, "entity_id": v.entity_id}
            for v in rows]


@router.post("/versions/{version_id}/revert")
async def revert_version(version_id: UUID, user: User = Depends(current_user),
                         db: AsyncSession = Depends(get_db)):
    entity = await versions_service.revert_version(db, user, version_id)
    return {"ok": True, "entity": row_snapshot(entity)}


# ---------- device integrations ----------

@router.get("/integrations/token")
async def get_token(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    return {"token": await devices.get_or_create_token(db, user)}


@router.post("/integrations/rotate")
async def rotate_token(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    return {"token": await devices.rotate_token(db, user)}


async def _ingest_user(request: Request, db: AsyncSession = Depends(get_db)) -> User:
    """Ingest authenticates with the per-user Bearer token, NOT the session cookie."""
    auth = request.headers.get("authorization", "")
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else None
    user = await devices.user_for_ingest_token(db, token)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid ingest token")
    return user


@router.post("/integrations/ingest")
async def ingest(data: IngestIn, user: User = Depends(_ingest_user), db: AsyncSession = Depends(get_db)):
    return await devices.ingest(db, user, data)


# ---------- search ----------

@router.get("/search")
async def search(q: str = Query(default=""), user: User = Depends(current_user),
                 db: AsyncSession = Depends(get_db)):
    if len(q.strip()) < 2:
        return {"foods": [], "recipes": [], "exercises": [], "conversations": []}
    return await search_service.search_all(db, user, q)


@router.get("/search/semantic")
async def search_semantic(q: str = Query(default=""), user: User = Depends(current_user),
                          db: AsyncSession = Depends(get_db)):
    if not q.strip():
        return {"results": []}
    return await search_service.semantic_search(db, user, q.strip())
