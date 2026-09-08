import time
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..ai import service as ai_service
from ..ai.registry import (detect_providers, get_ai_pref, mask_ai_pref, resolve_provider_from_pref,
                           save_ai_pref)
from ..db import get_db
from ..deps import current_user
from ..models import (AIAction, AIConversation, AIMessage, Recommendation, User, UserMemory,
                      UserPreference, UserProfile)
from ..schemas import (ActionOut, ChatIn, ChatOut, ConversationOut, MessageOut, OnboardingCommitIn,
                       OnboardingParseIn, RecommendationOut, RecommendationPatch)
from ..services import goals as goals_service
from ..services import habits as habits_service
from ..services import schedule as schedule_service
from ..services.common import audit, get_owned

router = APIRouter(prefix="/ai", tags=["ai"])


@router.post("/chat", response_model=ChatOut)
async def chat(data: ChatIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    conv, reply, actions = await ai_service.chat(db, user, data.message, data.conversation_id)
    return ChatOut(conversation_id=conv.id, reply=reply, actions=actions)


# ---------- provider selection ----------

@router.get("/providers")
async def list_providers(user: User = Depends(current_user)):
    return {"providers": await detect_providers()}


@router.get("/settings")
async def get_ai_settings(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    pref = (await db.execute(select(UserPreference).where(UserPreference.user_id == user.id))).scalar_one_or_none()
    return {"ai": mask_ai_pref(get_ai_pref(pref))}


class AISettingsIn(BaseModel):
    provider: str | None = None
    model: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    mode: str | None = None


@router.put("/settings")
async def put_ai_settings(data: AISettingsIn, user: User = Depends(current_user),
                          db: AsyncSession = Depends(get_db)):
    from ..ai.registry import AI_MODES
    if data.mode is not None and data.mode not in AI_MODES:
        raise HTTPException(422, f"mode must be one of {AI_MODES}")
    ai = {k: v for k, v in data.model_dump().items() if v is not None}
    return {"ai": await save_ai_pref(db, user, ai)}


@router.post("/test")
async def test_provider(data: AISettingsIn, user: User = Depends(current_user),
                        db: AsyncSession = Depends(get_db)):
    pref = (await db.execute(select(UserPreference).where(UserPreference.user_id == user.id))).scalar_one_or_none()
    merged = {**get_ai_pref(pref), **{k: v for k, v in data.model_dump().items() if v}}
    provider = resolve_provider_from_pref(merged)
    started = time.perf_counter()
    try:
        resp = await provider.complete(
            [{"role": "user", "content": "Reply with exactly: ok"}], tools=None)
        latency = int((time.perf_counter() - started) * 1000)
        text = (resp.text or "").strip()
        return {"ok": bool(text), "latency_ms": latency, "reply": text[:200]}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


@router.get("/conversations", response_model=list[ConversationOut])
async def list_conversations(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(AIConversation).where(AIConversation.user_id == user.id)
        .order_by(AIConversation.updated_at.desc()).limit(50)
    )
    return list(result.scalars().all())


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageOut])
async def get_messages(conversation_id: UUID, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    conv = await get_owned(db, AIConversation, conversation_id, user)
    result = await db.execute(
        select(AIMessage).where(AIMessage.conversation_id == conv.id).order_by(AIMessage.created_at).limit(200)
    )
    return list(result.scalars().all())


@router.get("/actions", response_model=list[ActionOut])
async def list_actions(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(AIAction).where(AIAction.user_id == user.id).order_by(AIAction.created_at.desc()).limit(50)
    )
    return list(result.scalars().all())


@router.post("/onboarding/parse")
async def onboarding_parse(data: OnboardingParseIn, user: User = Depends(current_user),
                           db: AsyncSession = Depends(get_db)):
    return await ai_service.parse_onboarding(db, user, data.text)


@router.post("/onboarding/commit")
async def onboarding_commit(data: OnboardingCommitIn, user: User = Depends(current_user),
                            db: AsyncSession = Depends(get_db)):
    profile = (await db.execute(select(UserProfile).where(UserProfile.user_id == user.id))).scalar_one_or_none()
    if profile is None:
        profile = UserProfile(user_id=user.id)
        db.add(profile)
        await db.flush()
    for key, value in data.profile.model_dump(exclude_none=True).items():
        if key == "dietary":
            profile.dietary = {**(profile.dietary or {}), **(value or {})}
        else:
            setattr(profile, key, value)
    profile.onboarding_completed = True

    created: dict[str, list] = {"goals": [], "targets": [], "events": [], "habits": [], "memories": []}
    for g in data.goals:
        goal = await goals_service.create_goal(db, user, g)
        created["goals"].append(str(goal.id))
    for t in data.targets:
        target = await goals_service.create_target(db, user, t)
        created["targets"].append(str(target.id))
    for e in data.events:
        try:
            event = await schedule_service.create_event(db, user, e)
            created["events"].append(str(event.id))
        except HTTPException:
            continue
    for h in data.habits:
        habit = await habits_service.create_habit(db, user, h)
        created["habits"].append(str(habit.id))
    for m in data.memories:
        mem = UserMemory(user_id=user.id, type=m.get("type", "preference"), key=m.get("key", "note"),
                         value={"value": m.get("value")}, source="user", confidence=1.0, status="active")
        db.add(mem)
    await audit(db, user.id, "onboarding_completed", "user", user.id, {k: len(v) for k, v in created.items()})
    await db.commit()
    return {"ok": True, "created": created}


@router.get("/recommendations", response_model=list[RecommendationOut])
async def list_recommendations(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    from ..services import recommendations as recs_service
    await recs_service.refresh_recommendations(db, user)
    result = await db.execute(
        select(Recommendation).where(Recommendation.user_id == user.id, Recommendation.status == "open")
        .order_by(Recommendation.created_at.desc()).limit(20)
    )
    return list(result.scalars().all())


@router.patch("/recommendations/{rec_id}", response_model=RecommendationOut)
async def update_recommendation(rec_id: UUID, patch: RecommendationPatch,
                                user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    rec = await get_owned(db, Recommendation, rec_id, user)
    rec.status = patch.status
    await db.commit()
    await db.refresh(rec)
    return rec
