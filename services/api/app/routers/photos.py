import base64
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..deps import current_user
from ..models import Photo, User
from ..storage import ALLOWED_TYPES, MAX_BYTES, delete_photo, read_photo, save_photo
from ..utils.time import user_today

router = APIRouter(prefix="/photos", tags=["photos"])


def _out(p: Photo) -> dict:
    return {"id": str(p.id), "category": p.category, "content_type": p.content_type,
            "size": p.size, "notes": p.notes, "date": p.date.isoformat() if p.date else None,
            "created_at": p.created_at.isoformat()}


@router.get("")
async def list_photos(category: str | None = None, user: User = Depends(current_user),
                      db: AsyncSession = Depends(get_db)):
    stmt = select(Photo).where(Photo.user_id == user.id)
    if category:
        stmt = stmt.where(Photo.category == category)
    result = await db.execute(stmt.order_by(Photo.created_at.desc()).limit(200))
    return [_out(p) for p in result.scalars().all()]


@router.post("", status_code=201)
async def upload_photo(file: UploadFile, category: str = "other", notes: str | None = None,
                       user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    content_type = file.content_type or "image/jpeg"
    if content_type not in ALLOWED_TYPES:
        raise HTTPException(415, f"Unsupported image type: {content_type}")
    content = await file.read()
    if len(content) > MAX_BYTES:
        raise HTTPException(413, "Image too large (max 15 MB)")
    key = save_photo(user.id, content, content_type)
    photo = Photo(user_id=user.id, category=category, storage_key=key, content_type=content_type,
                  size=len(content), notes=notes, date=user_today(user.timezone))
    db.add(photo)
    await db.commit()
    await db.refresh(photo)
    return _out(photo)


@router.get("/{photo_id}/file")
async def get_photo_file(photo_id: UUID, user: User = Depends(current_user),
                         db: AsyncSession = Depends(get_db)):
    photo = await db.get(Photo, photo_id)
    if photo is None or photo.user_id != user.id:
        raise HTTPException(404, "Photo not found")
    content = read_photo(photo.storage_key)
    if content is None:
        raise HTTPException(410, "File missing from storage")
    return Response(content, media_type=photo.content_type,
                    headers={"Cache-Control": "private, max-age=3600"})


@router.delete("/{photo_id}", status_code=204)
async def remove_photo(photo_id: UUID, user: User = Depends(current_user),
                       db: AsyncSession = Depends(get_db)):
    photo = await db.get(Photo, photo_id)
    if photo is None or photo.user_id != user.id:
        raise HTTPException(404, "Photo not found")
    delete_photo(photo.storage_key)
    await db.delete(photo)
    await db.commit()
    return None


@router.post("/{photo_id}/analyze")
async def analyze_photo(photo_id: UUID, user: User = Depends(current_user),
                        db: AsyncSession = Depends(get_db)):
    """Meal photo -> estimated items with explicit uncertainty.

    Requires a vision-capable provider (an OpenAI-compatible endpoint with a
    vision model). The offline mock and CLI providers decline honestly.
    """
    photo = await db.get(Photo, photo_id)
    if photo is None or photo.user_id != user.id:
        raise HTTPException(404, "Photo not found")
    content = read_photo(photo.storage_key)
    if content is None:
        raise HTTPException(410, "File missing from storage")

    from ..ai.provider import OpenAICompatibleProvider
    from ..ai.registry import provider_for_user

    provider = await provider_for_user(db, user)
    if not isinstance(provider, OpenAICompatibleProvider):
        return {"ok": False, "items": [],
                "message": "Photo analysis needs a vision-capable provider "
                           "(OpenAI-compatible endpoint with a vision model). "
                           "Switch providers in Settings → AI, or log the meal manually."}

    b64 = base64.b64encode(content).decode()
    prompt = (
        "Identify the foods in this meal photo. Return ONLY minified JSON: "
        '{"items": [{"name": str, "quantity": number, "unit": "g", "calories_est": number, '
        '"protein_est": number, "confidence": 0-1, "lower_kcal": number, "upper_kcal": number}]}. '
        "Always give ranges and honest confidence; never invent exactness."
    )
    try:
        async with __import__("httpx").AsyncClient(timeout=90) as client:
            resp = await client.post(
                f"{provider.base_url}/chat/completions",
                json={"model": provider.model, "messages": [{"role": "user", "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:{photo.content_type};base64,{b64}"}},
                ]}]},
                headers={"Authorization": f"Bearer {provider.api_key}"} if provider.api_key else {},
            )
            resp.raise_for_status()
            text = resp.json()["choices"][0]["message"]["content"] or ""
    except Exception as exc:
        return {"ok": False, "items": [], "message": f"Vision call failed: {type(exc).__name__}. "
                "You can still log the meal manually."}

    import json
    try:
        data = json.loads(text[text.find("{"):text.rfind("}") + 1])
        items = data.get("items", [])
    except (json.JSONDecodeError, ValueError):
        items = []
    return {"ok": bool(items), "items": items,
            "message": None if items else "Could not parse foods from the photo — log manually."}
