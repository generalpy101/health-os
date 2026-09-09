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


ONBOARDING_PROMPT = """You are setting up a personal health OS for a new user. Read their description and return ONLY minified JSON with this shape:
{"profile": {"age": number?, "height_cm": number?, "weight_kg": number?, "sex": "male|female"?, "activity_level": "sedentary|light|moderate|active|very_active"?},
 "goals": [{"type": "weight_loss|weight_gain|maintenance|muscle_gain|strength|endurance|fitness|sleep|hydration|habit|nutrition|activity|sport|custom", "title": str, "start_value": number?, "target_value": number?, "unit": str?}],
 "targets": [{"key": "workouts|swimming|steps|sleep_minutes", "value": number, "unit": str, "period": "daily|weekly"}],
 "events": [{"type": "workout|swimming|work|sleep|meal|custom", "title": str, "bydays": [0-6, Monday=0], "hour": 0-23, "end_hour": 0-23?}],
 "workout_plan": {"name": str, "days": [{"name": str, "exercises": [{"name": str, "sets": number, "reps": number}]}]}?,
 "memories": [{"type": "fact|preference", "key": snake_case, "value": str}],
 "dietary": {"diet": str?, "dislikes": [str]}}

Rules:
- Only include what the text supports. NEVER invent body stats or calorie numbers — calorie/protein
  targets are computed deterministically by the system from the profile you extract, so omit "calories"
  and "protein" targets entirely.
- Map current body weight to BOTH profile.weight_kg and the weight goal's start_value.
- If they state a training frequency (e.g. "train 4 times a week"), include a workout_plan: a sensible
  split for that frequency (2-3 days → full body; 4 → upper/lower; 5-6 → push/pull/legs variants) using
  basic compound exercises (squat, bench/press, row, overhead press, plank), 3 sets of 8-12 each.
- Schedule events should reflect their stated schedule: workouts on spread weekdays at their preferred
  time (default 18:00), work block weekdays if hours are given.

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
        p = data.get("profile") or {}
        birth_year = None
        if isinstance(p.get("age"), (int, float)) and p["age"] > 0:
            birth_year = user_now(user.timezone).year - int(p["age"])
        return _enrich_proposal({
            "profile": {
                "dietary": dietary,
                "activity_level": p.get("activity_level") or "moderate",
                "height_cm": p.get("height_cm"),
                "birth_year": birth_year,
                "sex": p.get("sex"),
                "onboarding_completed": True,
            },
            "weight_kg": p.get("weight_kg"),
            "goals": [g for g in data.get("goals", []) if isinstance(g, dict) and g.get("title")],
            "targets": [t for t in data.get("targets", []) if isinstance(t, dict) and t.get("key") and t.get("value")],
            "events": [e for e in data.get("events", []) if isinstance(e, dict) and e.get("title")],
            "workout_plan": data.get("workout_plan") if isinstance(data.get("workout_plan"), dict) else None,
            "habits": [],
            "memories": [m for m in data.get("memories", []) if isinstance(m, dict) and m.get("key")],
        })
    except Exception:
        return None


async def parse_onboarding(db: AsyncSession, user: User, text: str) -> dict:
    provider = await provider_for_user(db, user)
    if not isinstance(provider, MockProvider):
        parsed = await _parse_onboarding_llm(provider, text)
        if parsed is not None:
            return parsed
    return _parse_onboarding_keywords(text)


def _enrich_proposal(proposal: dict) -> dict:
    """Deterministic layer on top of any parser: compute suggested nutrition targets
    from body stats (Mifflin-St Jeor), propose a starter training plan from the
    detected weekly frequency. Never fabricates stats — only uses given numbers."""
    from ..utils import metrics as m

    profile = proposal.get("profile") or {}
    weight = proposal.get("weight_kg")
    if not isinstance(weight, (int, float)):
        weight = None
    height = profile.get("height_cm")
    age = None
    if profile.get("birth_year"):
        from ..utils.time import user_today
        age = user_today("UTC").year - int(profile["birth_year"])

    primary = (proposal.get("goals") or [{}])[0].get("type", "maintenance")
    suggested: list[dict] = []
    have = {t.get("key") for t in proposal.get("targets") or []}

    if weight and height and age:
        bmr = m.bmr_mifflin(weight, height, age, profile.get("sex"))
        tdee = m.tdee(bmr, profile.get("activity_level"))
        if tdee:
            if primary in ("weight_loss",):
                cal = max(1200, tdee - 500)
                reason = f"TDEE ≈{tdee} kcal (BMR {bmr} × activity) minus 500 kcal deficit"
            elif primary in ("weight_gain", "muscle_gain"):
                cal = tdee + 300
                reason = f"TDEE ≈{tdee} kcal plus 300 kcal surplus"
            else:
                cal = tdee
                reason = f"TDEE ≈{tdee} kcal (BMR {bmr} × activity)"
            if "calories" not in have:
                suggested.append({"key": "calories", "value": cal, "unit": "kcal", "period": "daily",
                                  "mode": "minimum", "source": "calculated", "reason": reason})
        protein = round(weight * (2.0 if primary in ("weight_loss", "muscle_gain") else 1.6))
        if "protein" not in have:
            suggested.append({"key": "protein", "value": protein, "unit": "g", "period": "daily",
                              "mode": "minimum", "source": "calculated",
                              "reason": f"{protein / weight:.1f} g/kg × {weight} kg body weight"})
    if "water" not in have:
        suggested.append({"key": "water", "value": 2500, "unit": "ml", "period": "daily", "mode": "minimum",
                          "source": "calculated", "reason": "sensible default; adjust to thirst and climate"})

    proposal["suggested_targets"] = suggested

    # starter training plan from detected weekly frequency — only when the parser didn't supply one
    llm_plan = proposal.get("workout_plan")
    if llm_plan and not (isinstance(llm_plan.get("days"), list) and llm_plan["days"]):
        proposal["workout_plan"] = None
        llm_plan = None
    freq = next((int(t["value"]) for t in (proposal.get("targets") or []) if t.get("key") == "workouts"), None)
    if freq and freq > 0 and not llm_plan:
        templates = {
            2: ["Full body A", "Full body B"],
            3: ["Full body A", "Full body B", "Full body C"],
            4: ["Upper A", "Lower A", "Upper B", "Lower B"],
            5: ["Push", "Pull", "Legs", "Upper", "Lower"],
            6: ["Push", "Pull", "Legs", "Push", "Pull", "Legs"],
        }
        day_names = templates.get(freq) or [f"Session {i + 1}" for i in range(freq)]
        base_exercises = ["Barbell Back Squat", "Barbell Bench Press", "Barbell Row", "Overhead Press", "Plank"]
        proposal["workout_plan"] = {
            "name": f"{freq}x/week starter",
            "days": [{"name": n, "exercises": [{"name": e, "sets": 3, "reps": 10} for e in base_exercises]}
                     for n in day_names],
        }
    return proposal


def _parse_onboarding_keywords(text: str) -> dict:
    """Keyword-based extraction (works offline). A hosted provider refines it later."""
    t = text.lower()
    goals_out: list[dict] = []
    targets: list[dict] = []
    events: list[dict] = []
    habits_out: list[dict] = []
    memories: list[dict] = []
    dietary: dict = {}

    # body stats: "25 yo", "173 cm", "82 kg", "male/female"
    age = None
    m_age = re.search(r"(\d{2})\s*(?:\s*yo\b|years?\s*old|y/?o\b)", t)
    if m_age:
        age = int(m_age.group(1))
    height_cm = None
    m_h = re.search(r"(\d{3}(?:\.\d+)?)\s*cm", t)
    if m_h:
        height_cm = float(m_h.group(1))
    weight_kg = None
    m_w = re.search(r"(?:^|\s)(\d{2,3}(?:\.\d+)?)\s*kg\b", t)
    if m_w and not re.search(r"from\s+" + re.escape(m_w.group(1)) + r"\s*kg\s*(?:to|->)", t):
        # a bare "82kg" that isn't part of a "from X to Y" range = current weight
        weight_kg = float(m_w.group(1))
    sex = None
    if re.search(r"\b(female|woman)\b", t):
        sex = "female"
    elif re.search(r"\b(male|man)\b", t):
        sex = "male"

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

    m = re.search(r"from\s+(\d+(?:\.\d+)?)\s*(?:kg)?\s*(?:to|->|down to)\s*(\d+(?:\.\d+)?)\s*kg", t)
    if m and goals_out:
        goals_out[0].update({"start_value": float(m.group(1)), "target_value": float(m.group(2)), "unit": "kg"})
        weight_kg = float(m.group(1))  # "from 82 to 74" → current weight is 82

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

    return _enrich_proposal({
        "profile": {
            "dietary": dietary,
            "activity_level": "moderate",
            "height_cm": height_cm,
            "birth_year": (user_now("UTC").year - age) if age else None,
            "sex": sex,
            "onboarding_completed": True,
        },
        "weight_kg": weight_kg,
        "goals": goals_out,
        "targets": targets,
        "events": events,
        "habits": habits_out,
        "memories": memories,
    })
