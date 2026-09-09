"""Chat orchestration: context assembly -> provider loop -> audited tool execution."""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import AsyncGenerator
from contextlib import suppress
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models import AIAction, AIConversation, AIMessage, User, UserMemory, UserProfile
from ..services import analytics as analytics_service
from ..services import goals as goals_service
from ..utils.time import user_now
from .provider import AIProvider, MockProvider
from .registry import provider_for_user
from .tools import REGISTRY, _s, execute_tool, tool_schemas

SYSTEM_PROMPT = """You are the assistant inside a personal health & fitness OS.
You operate the app through tools — never invent numbers; use tools to read real data
and to log or change things. Deterministic math (calories, trends, BMI) is done by the
system, not by you. Never present estimates as exact facts. Never give medical diagnoses;
for symptoms, medication, injuries or eating-disorder concerns, point to a professional.
Keep replies concise and concrete. When you change something, say what changed.

IMPORTANT — exactly-once logging: within a single reply, log each real-world item or event
exactly ONCE. If you need a custom food/exercise first, create it FIRST, then log once with it.
Never repeat a logging call with refined arguments; the user can edit instead.

Current user context:
{context}
"""


async def _context_block(db: AsyncSession, user: User) -> str:
    profile = (await db.execute(select(UserProfile).where(UserProfile.user_id == user.id))).scalar_one_or_none()
    targets = await goals_service.targets_map(db, user)
    active_goals = await goals_service.list_goals(db, user, status_filter="active")
    mems = (await db.execute(
        select(UserMemory).where(UserMemory.user_id == user.id, UserMemory.status == "active")
        .order_by(UserMemory.confidence.desc()).limit(12)
    )).scalars().all()
    try:
        summary = await analytics_service.daily_summary(db, user)
        today = {k: summary[k] for k in ("nutrition", "water_ml", "sleep_minutes", "workout_count",
                                         "habits_completed", "habits_total", "weight")}
    except Exception:
        today = {}
    return json.dumps({
        "name": user.name, "timezone": user.timezone, "units": user.units,
        "local_time": user_now(user.timezone).isoformat(timespec="minutes"),
        "profile": {
            "height_cm": profile.height_cm if profile else None,
            "activity_level": profile.activity_level if profile else None,
            "dietary": profile.dietary if profile else {},
        },
        "active_goals": [{"type": g.type, "title": g.title, "target": g.target_value, "unit": g.unit} for g in active_goals[:6]],
        "daily_targets": targets,
        "today": today,
        "memories": [{"type": m.type, "key": m.key, "value": m.value.get("value"), "confidence": m.confidence} for m in mems],
    }, default=str)


async def _get_conversation(db: AsyncSession, user: User, conversation_id: UUID | None) -> AIConversation:
    if conversation_id:
        conv = await db.get(AIConversation, conversation_id)
        if conv and conv.user_id == user.id:
            return conv
    conv = AIConversation(user_id=user.id)
    db.add(conv)
    await db.flush()
    return conv


async def _chat_core(db: AsyncSession, user: User, message: str, conversation_id: UUID | None = None,
                     provider: AIProvider | None = None, on_delta=None,
                     ) -> tuple[AIConversation, str, list[AIAction]]:
    """Shared chat loop for /ai/chat and /ai/chat/stream.

    When `on_delta` is given, provider rounds go through provider.stream() and text
    deltas are forwarded as they arrive; tool execution and ai_actions auditing are
    identical either way.
    """
    settings = get_settings()
    provider = provider or await provider_for_user(db, user)
    conv = await _get_conversation(db, user, conversation_id)
    db.add(AIMessage(conversation_id=conv.id, user_id=user.id, role="user", content=message))
    if conv.title == "Conversation":
        conv.title = message[:60].strip()
    await db.flush()

    history = (await db.execute(
        select(AIMessage).where(AIMessage.conversation_id == conv.id)
        .order_by(AIMessage.created_at.desc()).limit(20)
    )).scalars().all()
    history.reverse()

    context = await _context_block(db, user)
    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT.format(context=context)}]
    messages += [{"role": m.role, "content": m.content} for m in history if m.role in ("user", "assistant")]

    actions: list[AIAction] = []
    reply = ""
    for _round in range(settings.ai_max_tool_rounds):
        started = time.perf_counter()
        try:
            if on_delta is None:
                resp = await provider.complete(messages, tools=tool_schemas())
            else:
                resp = await provider.stream(messages, tools=tool_schemas(), on_delta=on_delta)
        except Exception as exc:
            reply = (f"The AI provider is unavailable right now ({type(exc).__name__}). "
                     "You can still use every screen and log manually — nothing here depends on AI.")
            break
        if not resp.tool_calls:
            reply = resp.text or "Done."
            break
        messages.append({"role": "assistant", "content": resp.text or "",
                         "tool_calls": [{"id": c.id, "type": "function",
                                         "function": {"name": c.name, "arguments": json.dumps(c.arguments)}}
                                        for c in resp.tool_calls]})
        seen_calls: set[str] = set()
        for call in resp.tool_calls:
            # guard: skip exact duplicate tool invocations within one turn
            fingerprint = f"{call.name}:{json.dumps(call.arguments, sort_keys=True)}"
            if fingerprint in seen_calls:
                continue
            seen_calls.add(fingerprint)
            latency = int((time.perf_counter() - started) * 1000)
            result = await execute_tool(db, user, call.name, call.arguments)
            risk = REGISTRY.get(call.name, (None, None, "low"))[2]
            status = "failed" if "error" in result else "executed"
            action = AIAction(user_id=user.id, conversation_id=conv.id, tool=call.name,
                              arguments=_s(call.arguments), result=_s(result), status=status,
                              model=resp.model or settings.ai_model, provider=provider.name,
                              latency_ms=latency)
            db.add(action)
            actions.append(action)
            messages.append({"role": "tool", "tool_call_id": call.id, "name": call.name,
                             "content": json.dumps(result, default=str)})
    else:
        reply = "I made several updates. Check the actions panel for details."

    if not reply:
        # summarize executed tool results into one assistant message
        summary_lines = []
        for a in actions:
            if a.status == "executed":
                summary_lines.append(f"{a.tool}: {json.dumps(a.result, default=str)[:200]}")
        reply = "Done.\n" + "\n".join(summary_lines[:6]) if summary_lines else "Sorry, that didn't work."

    db.add(AIMessage(conversation_id=conv.id, user_id=user.id, role="assistant", content=reply,
                     model=settings.ai_model))
    await db.commit()
    return conv, reply, actions


async def chat(db: AsyncSession, user: User, message: str, conversation_id: UUID | None = None,
               provider: AIProvider | None = None) -> tuple[AIConversation, str, list[AIAction]]:
    return await _chat_core(db, user, message, conversation_id, provider)


async def chat_stream(db: AsyncSession, user: User, message: str,
                      conversation_id: UUID | None = None) -> AsyncGenerator[dict, None]:
    """Streaming variant of chat(). Yields event dicts:
      {"type": "delta", "text": ...}            reply fragments as they arrive
      {"type": "actions", "actions": [...]}     audited tool actions (AIAction rows)
      {"type": "done", "conversation_id", "reply"}
      {"type": "error", "message": ...}         on unexpected failure
    """
    queue: asyncio.Queue[dict | None] = asyncio.Queue()

    async def on_delta(text: str) -> None:
        await queue.put({"type": "delta", "text": text})

    async def run() -> None:
        try:
            conv, reply, actions = await _chat_core(db, user, message, conversation_id, on_delta=on_delta)
            await queue.put({"type": "actions", "actions": [
                {"id": str(a.id), "tool": a.tool, "arguments": _s(a.arguments),
                 "result": _s(a.result), "status": a.status,
                 "created_at": a.created_at.isoformat() if a.created_at else None}
                for a in actions
            ]})
            await queue.put({"type": "done", "conversation_id": str(conv.id), "reply": reply})
        except Exception as exc:
            await queue.put({"type": "error", "message": f"{type(exc).__name__}: {exc}"})
        finally:
            await queue.put(None)

    task = asyncio.create_task(run())
    try:
        while True:
            event = await queue.get()
            if event is None:
                break
            yield event
    finally:
        if task.done():
            await task  # run() swallows handler errors into events; this just collects it
        else:
            task.cancel()  # client disconnected mid-stream
            with suppress(asyncio.CancelledError):
                await task


# ---------------------------------------------------------------------------
# Onboarding: natural language -> structured proposal (reviewed before commit)
# ---------------------------------------------------------------------------

DAY_WORDS = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4,
             "saturday": 5, "sunday": 6}
NUMBER_WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
                "six": 6, "seven": 7, "twice": 2, "thrice": 3}


ONBOARDING_PROMPT = """Extract a health/fitness setup from this user description. Return ONLY minified JSON with this shape:
{"goals": [{"type": "weight_loss|weight_gain|maintenance|muscle_gain|strength|endurance|fitness|sleep|hydration|habit|nutrition|activity|sport|custom", "title": str, "start_value": number?, "target_value": number?, "unit": str?}],
 "targets": [{"key": "calories|protein|water|steps|sleep_minutes|workouts|swimming", "value": number, "unit": str, "period": "daily|weekly"}],
 "events": [{"type": "workout|swimming|work|sleep|meal|custom", "title": str, "bydays": [0-6, Monday=0], "hour": 0-23, "end_hour": 0-23?}],
 "memories": [{"type": "fact|preference", "key": snake_case, "value": str}],
 "dietary": {"diet": str?, "dislikes": [str]}}
Only include what the text supports. Do not invent numbers.

USER TEXT:
%s"""


async def _parse_onboarding_llm(provider: AIProvider, text: str) -> dict | None:
    try:
        resp = await provider.complete(
            [{"role": "user", "content": ONBOARDING_PROMPT % text}], tools=None)
        raw = resp.text.strip()
        start, end = raw.find("{"), raw.rfind("}")
        if start == -1 or end <= start:
            return None
        data = json.loads(raw[start:end + 1])
        if not isinstance(data, dict) or "goals" not in data:
            return None
        dietary = data.get("dietary") or {}
        return {
            "profile": {"dietary": dietary, "activity_level": "moderate", "onboarding_completed": True},
            "goals": [g for g in data.get("goals", []) if isinstance(g, dict) and g.get("title")],
            "targets": [t for t in data.get("targets", []) if isinstance(t, dict) and t.get("key") and t.get("value")],
            "events": [e for e in data.get("events", []) if isinstance(e, dict) and e.get("title")],
            "habits": [],
            "memories": [m for m in data.get("memories", []) if isinstance(m, dict) and m.get("key")],
            "defaults_suggested": {"calories": 2000, "protein_g": 120, "water_ml": 2500},
        }
    except Exception:
        return None


async def parse_onboarding(db: AsyncSession, user: User, text: str) -> dict:
    provider = await provider_for_user(db, user)
    if not isinstance(provider, MockProvider):
        parsed = await _parse_onboarding_llm(provider, text)
        if parsed is not None:
            return parsed
    return _parse_onboarding_keywords(text)


def _parse_onboarding_keywords(text: str) -> dict:
    """Keyword-based extraction (works offline). A hosted provider refines it later."""
    t = text.lower()
    goals_out: list[dict] = []
    targets: list[dict] = []
    events: list[dict] = []
    habits_out: list[dict] = []
    memories: list[dict] = []
    dietary: dict = {}

    if re.search(r"lose (fat|weight)|fat loss|cut\b|lose\b", t):
        goals_out.append({"type": "weight_loss", "title": "Lose fat", "priority": "primary"})
    if re.search(r"(gain|build|put on).{0,12}muscle|muscle gain", t):
        goals_out.append({"type": "muscle_gain", "title": "Build muscle"})
    elif re.search(r"gain weight|bulk", t):
        goals_out.append({"type": "weight_gain", "title": "Gain weight"})
    if re.search(r"keep muscle|retain muscle|maintain muscle", t) and not any(g["type"] == "muscle_gain" for g in goals_out):
        memories.append({"type": "preference", "key": "training_focus", "value": "muscle retention"})
    if re.search(r"strength|stronger", t):
        goals_out.append({"type": "strength", "title": "Improve strength"})
    if re.search(r"endurance|stamina|cardio fitness", t):
        goals_out.append({"type": "endurance", "title": "Improve endurance"})
    if re.search(r"maintain|maintenance|stay (fit|healthy|lean)", t) and not goals_out:
        goals_out.append({"type": "maintenance", "title": "Maintain health"})
    if not goals_out:
        goals_out.append({"type": "custom", "title": text[:80].strip().capitalize()})

    m = re.search(r"(\d+(?:\.\d+)?)\s*kg\s*(?:to|->|down to)\s*(\d+(?:\.\d+)?)", t)
    if m and goals_out:
        goals_out[0].update({"start_value": float(m.group(1)), "target_value": float(m.group(2)), "unit": "kg"})

    # training frequency
    m = re.search(r"train(?:ing)?\s+(\w+)\s*(?:times?|days?)\s+a\s+week", t)
    if m:
        n = NUMBER_WORDS.get(m.group(1), 4)
        targets.append({"key": "workouts", "value": n, "unit": "sessions", "period": "weekly", "mode": "minimum"})
        days = [0, 2, 4, 6, 1, 3, 5][:n]
        events.append({"type": "workout", "title": "Gym session", "bydays": sorted(days), "hour": 18})
    m = re.search(r"swim(?:ming)?\s+(\w+)\s*(?:times?|days?)?\s*a\s+week", t)
    if m:
        n = NUMBER_WORDS.get(m.group(1), 2)
        targets.append({"key": "swimming", "value": n, "unit": "sessions", "period": "weekly", "mode": "minimum"})
        days = [1, 5, 3][:n]
        events.append({"type": "swimming", "title": "Swimming", "bydays": sorted(days), "hour": 7})

    # work schedule
    m = re.search(r"work(?:ing)?\s+(?:from\s+)?(\d{1,2})(?:\s*(?:am|pm))?\s*(?:to|until|-)\s*(\d{1,2})(?:\s*(?:am|pm))?", t)
    if m:
        h1, h2 = int(m.group(1)), int(m.group(2))
        h1 = h1 if h1 >= 7 else h1 + 12
        h2 = h2 if h2 > h1 else h2 + 12
        events.append({"type": "work", "title": "Work", "bydays": [0, 1, 2, 3, 4],
                       "hour": h1 % 24, "end_hour": h2 % 24})

    # diet
    if re.search(r"vegetarian", t):
        dietary["diet"] = "vegetarian"
    if re.search(r"vegan", t):
        dietary["diet"] = "vegan"
    for dislike in re.findall(r"(?:don't|do not|no)\s+(?:eat\s+)?(\w+(?:\s\w+)?)", t):
        if dislike not in ("like", "want"):
            dietary.setdefault("dislikes", []).append(dislike)
    if re.search(r"home.?cooked|home cooking|cook at home", t):
        memories.append({"type": "preference", "key": "meal_source", "value": "home-cooked"})
    if re.search(r"simple (meals|food|recipes)|quick meals|easy recipes", t):
        memories.append({"type": "preference", "key": "meal_complexity", "value": "low"})
    if re.search(r"gym access|access to a gym|have a gym", t):
        memories.append({"type": "fact", "key": "equipment_access", "value": "gym"})
    if re.search(r"late night|night owl|sleep around midnight|work late", t):
        memories.append({"type": "preference", "key": "chronotype", "value": "late"})

    m = re.search(r"sleep\s+(?:around\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", t)
    if "sleep" in t:
        targets.append({"key": "sleep_minutes", "value": 480, "unit": "min", "period": "daily", "mode": "minimum"})

    return {
        "profile": {"dietary": dietary, "activity_level": "moderate", "onboarding_completed": True},
        "goals": goals_out,
        "targets": targets,
        "events": events,
        "habits": habits_out,
        "memories": memories,
        "defaults_suggested": {"calories": 2000, "protein_g": 120, "water_ml": 2500},
    }
