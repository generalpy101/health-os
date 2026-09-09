import json
import time
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..ai import service as ai_service
from ..ai.registry import (detect_providers, get_ai_pref, mask_ai_pref, provider_for_user,
                           resolve_provider_from_pref, save_ai_pref)
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


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


@router.post("/chat/stream")
async def chat_stream(data: ChatIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    async def events():
        async for ev in ai_service.chat_stream(db, user, data.message, data.conversation_id):
            yield _sse(ev.pop("type"), ev)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------- provider selection ----------

@router.get("/providers")
async def list_providers(user: User = Depends(current_user)):
    return {"providers": await detect_providers()}


@router.get("/providers/{provider_id}/models")
async def list_provider_models(provider_id: str, base_url: str | None = None,
                               user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    from ..ai.registry import discover_models, get_ai_pref
    pref = (await db.execute(select(UserPreference).where(UserPreference.user_id == user.id))).scalar_one_or_none()
    saved = get_ai_pref(pref)
    return await discover_models(
        provider_id,
        base_url=base_url if base_url is not None else saved.get("base_url", ""),
        api_key=saved.get("api_key", ""),
    )


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
    """Mock provider answers inline (instant). Real providers run as a background
    job — CLI/hosted models can take a minute, and a long-held HTTP request is
    fragile (proxy resets on navigation). Poll GET /ai/jobs/{id} for the result."""
    from ..ai.provider import MockProvider
    from ..worker import enqueue

    provider = await provider_for_user(db, user)
    if isinstance(provider, MockProvider):
        return {"status": "done", "result": await ai_service.parse_onboarding(db, user, data.text)}
    job = await enqueue(db, "onboarding_parse", {"text": data.text}, user_id=user.id)
    await db.commit()
    return {"status": "pending", "job_id": str(job.id)}


@router.get("/jobs/{job_id}")
async def get_job(job_id: UUID, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    from ..models import BackgroundJob

    job = await db.get(BackgroundJob, job_id)
    if job is None or job.user_id != user.id:
        raise HTTPException(404, "Job not found")
    return {"id": str(job.id), "kind": job.kind, "status": job.status,
            "result": (job.payload or {}).get("result"),
            "error": job.last_error if job.status == "failed" else None}


@router.post("/onboarding/commit")
async def onboarding_commit(data: OnboardingCommitIn, user: User = Depends(current_user),
                            db: AsyncSession = Depends(get_db)):
    from ..models import Goal, ScheduleEvent, Target

    replaced = {"goals": 0, "targets": 0, "events": 0}
    if data.replace:
        # redo flow: retire the current setup before writing the new one
        old_goals = (await db.execute(
            select(Goal).where(Goal.user_id == user.id, Goal.status == "active"))).scalars().all()
        for g in old_goals:
            g.status = "archived"
            replaced["goals"] += 1
        old_targets = (await db.execute(
            select(Target).where(Target.user_id == user.id, Target.active.is_(True)))).scalars().all()
        for t in old_targets:
            t.active = False  # versioned by targets history via update path only when replaced per-key
            replaced["targets"] += 1
        old_events = (await db.execute(
            select(ScheduleEvent).where(ScheduleEvent.user_id == user.id))).scalars().all()
        for e in old_events:
            if (e.meta or {}).get("origin") == "onboarding":
                await db.delete(e)
                replaced["events"] += 1
        await db.flush()

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

    created: dict[str, list] = {"goals": [], "targets": [], "events": [], "habits": [], "memories": [], "plans": []}
    if data.weight_kg:
        from ..schemas import MeasurementIn
        from ..services import health as health_service
        await health_service.record_measurement(
            db, user, MeasurementIn(type="weight", value=data.weight_kg, unit="kg"))
    for g in data.goals:
        # backfill goal start_value from the recorded weight when missing
        if g.start_value is None and data.weight_kg and g.type in ("weight_loss", "weight_gain"):
            g.start_value = data.weight_kg
            g.unit = g.unit or "kg"
        goal = await goals_service.create_goal(db, user, g)
        created["goals"].append(str(goal.id))
    for t in data.targets:
        target = await goals_service.create_target(db, user, t)
        created["targets"].append(str(target.id))
    if data.workout_plan and data.workout_plan.get("days"):
        from ..schemas import WorkoutPlanIn
        from ..services import fitness as fitness_service
        plan = await fitness_service.create_plan(db, user, WorkoutPlanIn(
            name=data.workout_plan.get("name", "Starter plan"),
            days=data.workout_plan["days"],
        ))
        created["plans"].append(str(plan.id))
    for e in data.events:
        try:
            e.meta = {**(e.meta or {}), "origin": "onboarding"}
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
    await audit(db, user.id, "onboarding_completed", "user", user.id,
                {k: len(v) for k, v in created.items()} | {"replaced": replaced})
    await db.commit()
    return {"ok": True, "created": created, "replaced": replaced}


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
