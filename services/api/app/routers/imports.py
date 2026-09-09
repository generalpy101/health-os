from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..deps import current_user
from ..models import User
from ..schemas import ImportCommitIn, ImportCommitOut, ImportPreviewIn, ImportPreviewOut
from ..services import imports as import_service

router = APIRouter(tags=["imports"])


@router.post("/import/preview", response_model=ImportPreviewOut)
async def import_preview(data: ImportPreviewIn, user: User = Depends(current_user)):
    return import_service.preview(data)


@router.post("/import/commit", response_model=ImportCommitOut)
async def import_commit(data: ImportCommitIn, user: User = Depends(current_user),
                        db: AsyncSession = Depends(get_db)):
    return await import_service.commit(db, user, data)
