"""Web push subscriptions (VAPID). Delivery itself lives in services/push.py;
reminder scheduling is the worker's `check_reminders` job."""

from fastapi import APIRouter, Body, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..deps import current_user
from ..models import PushSubscription, User
from ..services import push as push_service

router = APIRouter(prefix="/push", tags=["push"])


class SubscribeIn(BaseModel):
    endpoint: str
    keys: dict  # {p256dh, auth}


@router.get("/vapid-key")
async def vapid_key(user: User = Depends(current_user)):
    return {"publicKey": push_service.public_key()}


@router.post("/subscribe", status_code=201)
async def subscribe(data: SubscribeIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    sub = (await db.execute(
        select(PushSubscription).where(PushSubscription.endpoint == data.endpoint)
    )).scalar_one_or_none()
    if sub is None:
        sub = PushSubscription(user_id=user.id, endpoint=data.endpoint)
        db.add(sub)
    sub.user_id = user.id  # re-subscribing the same browser adopts the row
    sub.keys = data.keys or {}
    await db.commit()
    return {"ok": True}


@router.delete("/subscribe", status_code=204)
async def unsubscribe(endpoint: str = Body(embed=True), user: User = Depends(current_user),
                      db: AsyncSession = Depends(get_db)):
    sub = (await db.execute(
        select(PushSubscription).where(PushSubscription.endpoint == endpoint)
    )).scalar_one_or_none()
    if sub is not None and sub.user_id == user.id:
        await db.delete(sub)
        await db.commit()


@router.post("/test")
async def test(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    sent = await push_service.send_to_user(db, user, "HealthOS", "HealthOS is wired up")
    await db.commit()  # persist any expired-subscription deletions
    return {"sent": sent}
