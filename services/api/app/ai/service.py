"""Chat orchestration: context assembly -> provider loop -> audited tool execution."""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import AsyncGenerator
from datetime import timedelta
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

SYSTEM_PROMPT = """You are the user's personal health & fitness coach inside their health OS — not a
generic chatbot. You know their goals, targets, schedule, preferences and recent behavior
(context below), and you operate the app through tools.

COACHING STYLE:
- Sound like a sharp, supportive human coach: direct, warm, specific. Short paragraphs.
- Always ground answers in THEIR data (targets, today's numbers, schedule, streaks, memories) —
  fetch with tools when the context block isn't enough.
- Recommend ONE clear next action when useful ("prioritize ~50g protein at dinner" beats a list of ten tips).
- Never moralize. Off-plan days are data, not failure — help them get the next choice right.
- Respect stated preferences (meal structure, cuisine, equipment, schedule) from memories; if a request
  conflicts with a preference, note the tradeoff briefly.
- If a goal has a target_date, you may mention time-frames using the local date in context.

OPERATING RULES:
- Act through tools — never invent numbers; deterministic math (calories, trends, BMI) is the system's job.
- Never present estimates as exact facts. Never diagnose; for symptoms, medication, injuries or
  eating-disorder concerns, point to a professional.
- When you change something, say exactly what changed. Keep it brief.
- Logging requests ("had X", "slept Y", "weighed Z"): log immediately, confirm with the key numbers,
  and add at most one short relevant observation (e.g. remaining calories) — no lectures.
- Exactly-once logging: within a single reply, log each real-world item or event exactly ONCE.
  If you need a custom food/exercise first, create it FIRST, then log once with it.
  Never repeat a logging call with refined arguments; the user can edit instead.
- Ambiguous log (no quantities, unclear which meal)? Log nothing; ask ONE focused question.

CURRENT USER CONTEXT (live, authoritative):
{context}
"""


async def _context_block(db: AsyncSession, user: User) -> str:
    from ..services import habits as habits_service
    from ..services import health as health_service
    from ..services import schedule as schedule_service

    profile = (await db.execute(select(UserProfile).where(UserProfile.user_id == user.id))).scalar_one_or_none()
    targets = await goals_service.targets_map(db, user)
    active_goals = await goals_service.list_goals(db, user, status_filter="active")
    mems = (await db.execute(
        select(UserMemory).where(UserMemory.user_id == user.id, UserMemory.status == "active")
        .order_by(UserMemory.confidence.desc()).limit(12)
    )).scalars().all()

    ctx: dict = {}
    try:
        summary = await analytics_service.daily_summary(db, user)
        ctx["today"] = {k: summary[k] for k in ("nutrition", "water_ml", "sleep_minutes", "workout_count",
                                                "habits_completed", "habits_total", "weight")}
        ctx["today"]["schedule"] = [{"title": e["title"], "type": e["type"],
                                     "start": e["start_at"].isoformat()} for e in summary["schedule"][:6]]
    except Exception:
        pass
    try:
        today = user_now(user.timezone).date()
        tomorrow_events = await schedule_service.get_schedule(db, user, today + timedelta(days=1), today + timedelta(days=1))
        ctx["tomorrow"] = [{"title": e["title"], "type": e["type"], "start": e["start_at"].isoformat()}
                           for e in tomorrow_events[:6]]
    except Exception:
        pass
    try:
        ctx["habit_streaks"] = [{"name": h["name"], "streak": h["streak"], "done_today": h["today_status"] == "completed"}
                                for h in await habits_service.habit_progress(db, user, days=1)]
    except Exception:
        pass
    try:
        trend = await health_service.weight_trend(db, user, today - timedelta(days=30), today)
        if trend["points"]:
            ctx["weight_trend"] = {"latest": trend["points"][-1]["value"],
                                   "weekly_rate": trend["weekly_rate"], "points_30d": len(trend["points"])}
    except Exception:
        pass

    return json.dumps({
        "name": user.name, "timezone": user.timezone, "units": user.units,
        "local_time": user_now(user.timezone).isoformat(timespec="minutes"),
        "profile": {
            "height_cm": profile.height_cm if profile else None,
            "activity_level": profile.activity_level if profile else None,
            "dietary": profile.dietary if profile else {},
        },
        "active_goals": [{"type": g.type, "title": g.title, "target": g.target_value, "unit": g.unit,
                          "target_date": str(g.target_date) if g.target_date else None} for g in active_goals[:6]],
        "daily_targets": targets,
        "memories": [{"type": m.type, "key": m.key, "value": m.value.get("value"), "confidence": m.confidence} for m in mems],
        **ctx,
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
                     provider: AIProvider | None = None, on_delta=None, on_trace=None,
                     ) -> tuple[AIConversation, str, list[AIAction]]:
    """Shared chat loop for /ai/chat and /ai/chat/stream.

    When `on_delta` is given, provider rounds go through provider.stream() and text
    deltas are forwarded as they arrive; tool execution and ai_actions auditing are
    identical either way. `on_trace` receives progress events (thinking/heartbeat/
    tool_start/tool_end/thought) so the UI can show live reasoning progress.
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
    t0 = time.perf_counter()

    async def trace(payload: dict) -> None:
        if on_trace is not None:
            await on_trace({**payload, "elapsed_s": round(time.perf_counter() - t0, 1)})

    async def call_provider() -> Any:
        """Run the provider with 5s heartbeat traces so slow CLIs show life."""
        async def _call() -> Any:
            if on_delta is None:
                return await provider.complete(messages, tools=tool_schemas())
            return await provider.stream(messages, tools=tool_schemas(), on_delta=on_delta)

        task = asyncio.create_task(_call())
        while not task.done():
            try:
                return await asyncio.wait_for(asyncio.shield(task), timeout=5)
            except asyncio.TimeoutError:
                await trace({"kind": "heartbeat"})
        return task.result()  # raises if the provider failed

    for _round in range(settings.ai_max_tool_rounds):
        started = time.perf_counter()
        await trace({"kind": "thinking", "round": _round + 1})
        try:
            resp = await call_provider()
        except Exception as exc:
            reply = (f"The AI provider is unavailable right now ({type(exc).__name__}). "
                     "You can still use every screen and log manually — nothing here depends on AI.")
            await trace({"kind": "error", "detail": type(exc).__name__})
            break
        await trace({"kind": "thought", "ms": int((time.perf_counter() - started) * 1000)})
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
            await trace({"kind": "tool_start", "tool": call.name})
            tool_started = time.perf_counter()
            latency = int((time.perf_counter() - started) * 1000)
            result = await execute_tool(db, user, call.name, call.arguments)
            tool_ms = int((time.perf_counter() - tool_started) * 1000)
            risk = REGISTRY.get(call.name, (None, None, "low"))[2]
            status = "failed" if "error" in result else "executed"
            action = AIAction(user_id=user.id, conversation_id=conv.id, tool=call.name,
                              arguments=_s(call.arguments), result=_s(result), status=status,
                              model=resp.model or settings.ai_model, provider=provider.name,
                              latency_ms=latency)
            db.add(action)
            actions.append(action)
            await trace({"kind": "tool_end", "tool": call.name, "status": status, "ms": tool_ms})
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

    async def on_trace(payload: dict) -> None:
        await queue.put({"type": "trace", **payload})

    async def run() -> None:
        t0 = time.perf_counter()
        try:
            conv, reply, actions = await _chat_core(db, user, message, conversation_id,
                                                    on_delta=on_delta, on_trace=on_trace)
            await queue.put({"type": "actions", "actions": [
                {"id": str(a.id), "tool": a.tool, "arguments": _s(a.arguments),
                 "result": _s(a.result), "status": a.status,
                 "created_at": a.created_at.isoformat() if a.created_at else None}
                for a in actions
            ]})
            await queue.put({"type": "done", "conversation_id": str(conv.id), "reply": reply,
                             "elapsed_s": round(time.perf_counter() - t0, 1)})
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


ONBOARDING_PROMPT = """You are setting up a personal health OS for a new user. Read their description carefully and return ONLY minified JSON with this exact shape:
{"profile": {"age": number?, "height_cm": number?, "weight_kg": number?, "sex": "male|female"?, "activity_level": "sedentary|light|moderate|active|very_active"?},
 "goals": [{"type": "weight_loss|weight_gain|maintenance|muscle_gain|strength|endurance|fitness|sleep|hydration|habit|nutrition|activity|sport|custom", "title": str, "start_value": number?, "target_value": number?, "unit": str?, "target_date": "YYYY-MM-DD"?}],
 "targets": [{"key": "calories|protein|water|steps|sleep_minutes|workouts|swimming", "value": number, "unit": str, "period": "daily|weekly", "mode": "minimum|range"?, "range_low": number?, "range_high": number?}],
 "events": [{"type": "workout|swimming|work|sleep|meal|custom", "title": str, "bydays": [0-6, Monday=0], "hour": 0-23, "minute": 0-59?, "end_hour": 0-23?}],
 "workout_plan": {"name": str, "days": [{"name": str, "exercises": [{"name": str, "sets": number, "reps": number}]}]}?,
 "habits": [{"name": str}]?,
 "memories": [{"type": "fact|preference", "key": snake_case, "value": str}],
 "dietary": {"diet": str?, "dislikes": [str]}}

Extraction rules:
- Only include what the text supports. Map current body weight to BOTH profile.weight_kg and the weight goal's start_value. If they give a goal deadline/date, set target_date.
- If they state explicit calorie/protein numbers (even as a range like "1900–2000 kcal" or "120–140g protein"), include them as user targets (value = lower bound; mode "range" with range_low/range_high when a range). The system never overrides explicitly stated numbers.
- Training frequency → workouts weekly target (range like "3–4 times" → lower bound) + workout_plan with a sensible split (2-3 days → full body; 4 → upper/lower; 5-6 → push/pull/legs variants) of basic compound exercises, 3×8-12 each.
- Steps per day (range → lower bound), water, sleep duration → sleep_minutes (default 480 when they only mention bedtime).
- Schedule MUST respect their actual rhythm, not a 9–5 assumption: night-shift work blocks, late gym times, sleep events at their stated bedtime. Spread training across the week with rest days between hard days.
- Memories: meal structure (e.g. "2 meals + 1-2 protein snacks"), cuisine, staple preferences (rice over roti), equipment (induction, air fryer…), supplements they already take (creatine, protein powder with g/scoop if stated), chronotype, wake/bed times, cooking time limits, girlfriend/schedule constraints worth remembering.
- Habits for daily supplement use (e.g. "Take creatine").
- Dietary: diet type + dislikes ONLY when they explicitly say they don't eat/avoid something.

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
            "habits": [h for h in data.get("habits", []) if isinstance(h, dict) and h.get("name")],
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

    # body stats: "25 yo", "24-year-old", "173 cm", "82 kg", "male/female"
    age = None
    m_age = re.search(r"(\d{2})\s*(?:-?\s*(?:yo\b|y/?o\b|years?[-\s]old))", t)
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

    # training frequency: "train four times a week", "gym 3–4 times per week", "gym 3 times a week"
    def _weekly_freq(patterns: list[str]) -> int | None:
        for pat in patterns:
            m = re.search(pat, t)
            if not m:
                continue
            g = m.group(1)
            if g.isdigit():
                # range "3–4" → take the lower bound as the sustainable minimum
                lo = g
                return int(lo)
            return NUMBER_WORDS.get(g)
        return None

    n_gym = _weekly_freq([
        r"(?:train(?:ing)?|gym|work\s*out|lift)[a-z\s]*?(\d)\s*(?:–|-|to)\s*\d\s*times?\s*(?:per|a)\s*week",
        r"(?:train(?:ing)?|gym|work\s*out|lift)[a-z\s]*?(\w+)\s*(?:(?:times?|days?)\s*)?(?:per|a)\s*week",
    ])
    if n_gym:
        targets.append({"key": "workouts", "value": n_gym, "unit": "sessions", "period": "weekly", "mode": "minimum"})
        days = [0, 2, 4, 6, 1, 3, 5][:n_gym]
        events.append({"type": "workout", "title": "Gym session", "bydays": sorted(days), "hour": 18})
    n_swim = _weekly_freq([
        r"swim(?:ming)?[a-z\s]*?(\d)\s*(?:–|-|to)\s*\d\s*times?\s*(?:per|a)\s*week",
        r"swim(?:ming)?[a-z\s]*?(\w+)\s*(?:(?:times?|days?)\s*)?(?:per|a)\s*week",
    ])
    if n_swim:
        targets.append({"key": "swimming", "value": n_swim, "unit": "sessions", "period": "weekly", "mode": "minimum"})
        days = [1, 5, 3][:n_swim]
        events.append({"type": "swimming", "title": "Swimming", "bydays": sorted(days), "hour": 7})

    # steps: "7,000–10,000 steps per day" → lower bound as the daily minimum
    m_steps = re.search(r"([\d,]{4,})\s*(?:–|-|to)\s*([\d,]{4,})\s*steps", t) or re.search(r"([\d,]{4,})\s*steps", t)
    if m_steps:
        steps = int(m_steps.group(1).replace(",", ""))
        targets.append({"key": "steps", "value": steps, "unit": "steps", "period": "daily", "mode": "minimum"})

    # explicit nutrition targets win over computed suggestions:
    # "start around 1,900–2,000 calories", "aim for 120–140g of protein"
    m_cal = re.search(r"([\d,]{4,})\s*(?:–|-|to)\s*([\d,]{4,})\s*(?:kcal|calories)\b", t) or \
        re.search(r"(?:around|about|~)?\s*([\d,]{4,})\s*(?:kcal|calories)\b", t)
    if m_cal:
        lo = int(m_cal.group(1).replace(",", ""))
        hi = int(m_cal.group(2).replace(",", "")) if m_cal.lastindex and m_cal.lastindex >= 2 else None
        targets.append({"key": "calories", "value": lo, "unit": "kcal", "period": "daily",
                        "mode": "range" if hi else "minimum",
                        **({"range_low": lo, "range_high": hi} if hi else {}),
                        "source": "user", "reason": "stated in your setup"})
    m_pro = re.search(r"(\d{2,3})\s*(?:–|-|to)\s*(\d{2,3})\s*g\s*(?:of\s*)?protein", t) or \
        re.search(r"(\d{2,3})\s*g\s*(?:of\s*)?protein", t)
    if m_pro:
        lo = int(m_pro.group(1))
        hi = int(m_pro.group(2)) if m_pro.lastindex and m_pro.lastindex >= 2 else None
        targets.append({"key": "protein", "value": lo, "unit": "g", "period": "daily",
                        "mode": "range" if hi else "minimum",
                        **({"range_low": lo, "range_high": hi} if hi else {}),
                        "source": "user", "reason": "stated in your setup"})

    # work schedule: "work from 10 to 7", "work from around 10:30 PM until the morning"
    m = re.search(r"work(?:ing)?\s+(?:from\s+)?(?:around\s+|about\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\s*(?:to|until|-)\s*(?:the\s+morning|(\d{1,2})(?::(\d{2}))?\s*(am|pm)?)", t)
    if m:
        h1 = int(m.group(1)) % 24
        if (m.group(3) == "pm" or (m.group(3) is None and h1 < 7)) and h1 < 12:
            h1 += 12
        if m.group(4):
            h2 = int(m.group(4)) % 24
            if (m.group(6) == "pm" or m.group(6) is None) and h2 < 12:
                h2 += 12
            if h2 <= h1:
                h2 = (h2 + 12) % 24 or 6
        else:
            h2 = 6  # "until the morning"
        events.append({"type": "work", "title": "Work", "bydays": [0, 1, 2, 3, 4],
                       "hour": h1, "minute": int(m.group(2) or 0), "end_hour": h2})

    # diet — only extract from a known food/allergen vocabulary; never guess from grammar
    if re.search(r"vegetarian", t):
        dietary["diet"] = "vegetarian"
    if re.search(r"vegan", t):
        dietary["diet"] = "vegan"
    KNOWN_DISLIKES = ["seafood", "fish", "dairy", "milk", "nuts", "peanuts", "gluten", "eggs",
                      "soy", "spicy food", "pork", "beef", "shellfish", "mushrooms"]
    for food in KNOWN_DISLIKES:
        if re.search(rf"(?:don't|do not|don't|no|dislike|hate|avoid|allergic\w*\s+to)\s+\w*\s*{re.escape(food)}\b", t):
            dietary.setdefault("dislikes", []).append(food)

    # meal structure / preferences
    m_meals = re.search(r"[^.]*(?:meals?\s+(?:per|a)\s+day|protein[-\s]focused\s+snacks?)[^.]*", t)
    if m_meals and re.search(r"meals?", m_meals.group(0)):
        memories.append({"type": "preference", "key": "meal_structure",
                         "value": re.sub(r"\s+", " ", m_meals.group(0)).strip()[:160]})
    if re.search(r"under\s+(\d+)\s*min", t):
        memories.append({"type": "preference", "key": "max_cook_minutes",
                         "value": re.search(r"under\s+(\d+)\s*min", t).group(1)})
    if re.search(r"rice over roti|prefer rice|prefers rice", t):
        memories.append({"type": "preference", "key": "staple_preference", "value": "rice"})
    if re.search(r"indian", t):
        memories.append({"type": "preference", "key": "cuisine", "value": "Indian home-cooked"})

    # supplements → habits + memories (so the AI accounts for them instead of re-recommending)
    if re.search(r"creatine", t):
        habits_out.append({"name": "Take creatine"})
        memories.append({"type": "fact", "key": "supplement", "value": "creatine"})
    m_protein_powder = re.search(r"([\w\s-]*?protein powder)[^.]*?(\d+)\s*g\s*protein\s+per\s+scoop", t)
    if m_protein_powder:
        memories.append({"type": "fact", "key": "protein_powder",
                         "value": f"{m_protein_powder.group(1).strip()}, ~{m_protein_powder.group(2)}g protein per scoop"})
    elif re.search(r"protein (powder|shake)", t):
        memories.append({"type": "fact", "key": "protein_powder", "value": "uses protein powder"})

    # equipment available (normalized; "airfryer" and "air fryer" are one thing)
    EQUIP_ALIASES = {"airfryer": "air fryer"}
    equipment = set()
    t_flat = t.replace(" ", "")
    for e in ["induction", "air fryer", "airfryer", "oven", "microwave", "blender", "gym", "pool"]:
        if e.replace(" ", "") in t_flat:
            equipment.add(EQUIP_ALIASES.get(e, e))
    if equipment:
        memories.append({"type": "fact", "key": "kitchen_equipment", "value": ", ".join(sorted(equipment))})

    # chronotype / sleep times
    if re.search(r"night[- ]?(owl|oriented)|late/night|late nights|work late", t):
        memories.append({"type": "preference", "key": "chronotype", "value": "night-oriented"})
    m_sleep = re.search(r"sleep\s+(?:around\s+)?(\d{1,2})(?:\s*(?:–|-|to)\s*(\d{1,2}))?\s*(am|pm)", t)
    if m_sleep:
        h = int(m_sleep.group(1)) % 12
        if m_sleep.group(3) == "pm":
            h += 12
        memories.append({"type": "preference", "key": "usual_bedtime", "value": f"~{h}:00"})
    m_wake = re.search(r"wake\s+up\s+around\s+(\d{1,2})\s*(am|pm)?", t)
    if m_wake:
        h = int(m_wake.group(1)) % 12
        if m_wake.group(2) == "pm" or (m_wake.group(2) is None and h < 7):
            h += 12
        memories.append({"type": "preference", "key": "usual_wake", "value": f"~{h}:00"})
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
