"""AI provider abstraction. The rest of the app never depends on a concrete provider."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

import httpx

from ..config import get_settings


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ProviderResponse:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    model: str = ""
    usage: dict[str, int] = field(default_factory=dict)


class AIProvider:
    name = "base"

    async def complete(self, messages: list[dict], tools: list[dict] | None = None) -> ProviderResponse:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Mock provider: deterministic, offline, keyword/regex based intent parsing.
# Keeps the whole product functional with zero external AI dependencies.
# ---------------------------------------------------------------------------

NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}

MEAL_WORDS = ["breakfast", "brunch", "lunch", "snack", "dinner", "dessert"]
DAY_WORDS = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4,
             "saturday": 5, "sunday": 6}


def _num(token: str) -> float | None:
    token = token.strip().lower()
    if token in NUMBER_WORDS:
        return float(NUMBER_WORDS[token])
    try:
        return float(token)
    except ValueError:
        return None


def _extract_qty_unit(text: str) -> tuple[float, str] | None:
    m = re.match(r"^(\d+(?:\.\d+)?)\s*(g|kg|ml|l|oz|kcal|cal|calories|hours?|hrs?|h|minutes?|mins?|m|km|mi|steps)?\b", text)
    if not m:
        return None
    value = float(m.group(1))
    unit = (m.group(2) or "").lower()
    return value, unit


def _mock_tool_calls(message: str) -> tuple[list[ToolCall], str]:
    """Map natural language onto tool calls. Returns (tool_calls, reply_hint)."""
    text = message.lower().strip()
    calls: list[ToolCall] = []
    n = 0

    def call(name: str, args: dict) -> None:
        nonlocal n
        n += 1
        calls.append(ToolCall(id=f"mock-{n}", name=name, arguments=args))

    # --- water ---
    m = re.search(r"(\d+(?:\.\d+)?)\s*(ml|l|litre?s?|liters?)\b.{0,20}(water|drank|drink)", text) or \
        re.search(r"(?:water|drank|drink).{0,20}(\d+(?:\.\d+)?)\s*(ml|l|litre?s?|liters?)\b", text)
    if m and "water" in text or (m and re.search(r"drank|drink|hydration", text)):
        value, unit = float(m.group(1)), m.group(2)
        amount = value * 1000 if unit.startswith("l") and unit != "ml" else value
        call("log_water", {"amount_ml": amount})
        return calls, "water"

    # --- weight ---
    m = re.search(r"(?:weigh(?:ed|s)?(?:\s+in)?(?:\s+at)?|weight\s+(?:is|was|=)?)\s*(\d+(?:\.\d+)?)\s*(kg|kilos?|lb|lbs?)?", text)
    if m:
        value = float(m.group(1))
        unit = "lb" if (m.group(2) or "kg").startswith("lb") else "kg"
        call("record_measurement", {"type": "weight", "value": value, "unit": unit})
        return calls, "weight"

    # --- sleep ---
    m = re.search(r"slept\s+(?:for\s+)?(\d+(?:\.\d+)?)\s*(?:hours?|hrs?|h)\b", text)
    if m:
        call("log_sleep_hours", {"hours": float(m.group(1))})
        return calls, "sleep"
    m = re.search(r"slept\s+(?:from\s+)?(\d{1,2})[:.](\d{2})\s*(?:to|until|-)\s*(\d{1,2})[:.](\d{2})", text)
    if m:
        h1, m1, h2, m2 = (int(g) for g in m.groups())
        call("log_sleep_times", {"start": f"{h1:02d}:{m1:02d}", "end": f"{h2:02d}:{m2:02d}"})
        return calls, "sleep"

    # --- targets ---
    m = re.search(r"(?:set|change|update)\s+(?:my\s+)?(protein|calorie|calories|water|steps|sleep)\s*(?:target|goal)?\s*(?:to|=)\s*(\d+(?:\.\d+)?)\s*(g|kg|kcal|cal|ml|l|hours?|h)?", text)
    if m:
        key_raw, value, unit = m.group(1), float(m.group(2)), (m.group(3) or "")
        key = {"calorie": "calories", "calories": "calories"}.get(key_raw, key_raw)
        if key == "water":
            value = value * 1000 if unit.startswith("l") else value
            unit = "ml"
        elif key == "protein":
            unit = "g"
        elif key == "calories":
            unit = "kcal"
        elif key == "steps":
            unit = "steps"
        elif key == "sleep":
            value = value * 60 if unit.startswith("h") else value
            key, unit = "sleep_minutes", "min"
        call("create_target", {"key": key, "value": value, "unit": unit or "", "period": "daily", "mode": "minimum"})
        return calls, "target"

    # --- schedule recurring ---
    m = re.search(r"(?:schedule|plan)\s+([\w\s]+?)\s+(\w+)\s+times?\s+a\s+week", text)
    if m:
        call("create_schedule_event", {"title": m.group(1).strip().title(), "type": "custom",
                                       "times_per_week": int(m.group(2)) if m.group(2).isdigit() else NUMBER_WORDS.get(m.group(2), 2)})
        return calls, "schedule"
    if re.search(r"\bevery\b", text) and any(d in text for d in DAY_WORDS):
        days = [v for k, v in DAY_WORDS.items() if k in text]
        title = re.sub(r"\b(every|schedule|add|on|at)\b", "", text).strip()
        for day_word in DAY_WORDS:
            title = title.replace(day_word, "").strip()
        hm = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", text)
        hour = 18
        if hm:
            hour = int(hm.group(1)) % 24
            if hm.group(3) == "pm" and hour < 12:
                hour += 12
            if hm.group(3) is None and hour < 6:
                hour += 12
        call("create_schedule_event", {"title": title.title() or "Session", "type": "workout",
                                       "bydays": days, "hour": hour, "minute": int(hm.group(2) or 0) if hm else 0})
        return calls, "schedule"

    # --- goals ---
    m = re.search(r"(?:i want to|my goal is to|goal:?)\s*(.+)", text)
    if m and re.search(r"lose|gain|build|improve|maintain|train|muscle|weight|strength|sleep|habit", text):
        desc = m.group(1).strip()
        goal_type = "custom"
        if re.search(r"lose|fat|cut", desc):
            goal_type = "weight_loss"
        elif re.search(r"gain|bulk", desc):
            goal_type = "weight_gain"
        elif re.search(r"muscle|build", desc):
            goal_type = "muscle_gain"
        elif re.search(r"strength|strong", desc):
            goal_type = "strength"
        elif re.search(r"sleep", desc):
            goal_type = "sleep"
        elif re.search(r"maintain", desc):
            goal_type = "maintenance"
        args: dict[str, Any] = {"type": goal_type, "title": desc[:200].capitalize()}
        rng = re.search(r"from\s+(\d+(?:\.\d+)?)\s*(?:to|->)\s*(\d+(?:\.\d+)?)", desc)
        if rng:
            args.update({"start_value": float(rng.group(1)), "target_value": float(rng.group(2)), "unit": "kg"})
        else:
            single = re.search(r"(\d+(?:\.\d+)?)\s*kg", desc)
            if single:
                args.update({"target_value": float(single.group(1)), "unit": "kg"})
        call("create_goal", args)
        return calls, "goal"

    # --- habits ---
    if re.search(r"habit|remind me to|every day i (will|want to)", text) and re.search(r"create|add|start|track", text):
        name = re.sub(r"(create|add|start|track|a|habit|remind me to|every day i will|every day i want to)", "", text).strip()
        call("create_habit", {"name": (name or text)[:160].capitalize()})
        return calls, "habit"

    # --- summary / progress questions ---
    if re.search(r"how (am i|have i)|summary|progress|on track|how.*weight.*(changed|month|week)", text):
        call("get_daily_summary", {})
        call("get_weight_trend", {})
        return calls, "summary"

    # --- workout logging: "did chest workout", "bench 3x10 at 60kg" ---
    m = re.search(r"(?:did|logged?|completed|finished)\s+(?:a\s+|my\s+)?([\w\s]{2,40}?)\s*workout", text)
    if m:
        call("log_workout", {"title": m.group(1).strip().title() + " Workout", "exercises": []})
        return calls, "workout"
    m = re.search(r"([\w\s]{3,30}?)\s+(\d+)\s*x\s*(\d+)\s*(?:at|@|with)?\s*(\d+(?:\.\d+)?)?\s*(kg|lb)?", text)
    if m and re.search(r"bench|squat|deadlift|press|row|curl|pull|push|lift", text):
        exercise = m.group(1).strip().title()
        sets, reps = int(m.group(2)), int(m.group(3))
        weight = float(m.group(4)) if m.group(4) else None
        call("log_workout", {"title": f"{exercise} Session",
                             "exercises": [{"name": exercise, "sets": [{"weight": weight, "reps": reps}] * sets}]})
        return calls, "workout"

    # --- habit completion: "meditated", "took creatine" ---
    m = re.search(r"(?:i\s+)?(meditated|took|did|completed|finished)\s+(?:my\s+)?([\w\s]{2,40})", text)
    if m and re.search(r"creatine|vitamin|meditat|read|stretch|walk|medication|habit", text):
        call("log_habit_by_name", {"name": (m.group(2) or m.group(1)).strip()})
        return calls, "habit_log"

    # --- food logging ---
    if re.search(r"\b(ate|had|eat|eaten|log|add|having)\b", text) and re.search(
            r"\b(egg|eggs|rice|dal|toast|chicken|oats|milk|banana|bread|salad|meal|food|lunch|dinner|breakfast|snack|protein)\b", text):
        meal = next((w for w in MEAL_WORDS if w in text), None)
        body = re.sub(r"\b(for|as|at|my|i|log|add|ate|had|eaten?)\b", " ", text)
        for w in MEAL_WORDS:
            body = body.replace(w, " ")
        items = []
        for chunk in re.split(r",| and | with ", body):
            chunk = chunk.strip()
            if not chunk:
                continue
            m2 = re.match(r"^(\d+(?:\.\d+)?|one|two|three|four|five|six)\s*(g|kg|ml|l)?\s+(.+)$", chunk)
            if m2:
                qty = _num(m2.group(1)) or 1
                unit = m2.group(2) or "serving"
                name = m2.group(3).strip()
                if unit == "kg":
                    qty, unit = qty * 1000, "g"
                elif unit == "l":
                    qty, unit = qty * 1000, "ml"
                items.append({"name": name, "quantity": qty, "unit": unit})
            else:
                m3 = re.match(r"^(\d+(?:\.\d+)?)(g|kg|ml)\s*(.+)$", chunk)
                if m3:
                    qty = float(m3.group(1))
                    unit = m3.group(2)
                    if unit == "kg":
                        qty, unit = qty * 1000, "g"
                    items.append({"name": m3.group(3).strip(), "quantity": qty, "unit": unit})
                elif len(chunk) > 1 and not re.search(r"^\W+$", chunk):
                    items.append({"name": chunk, "quantity": 1, "unit": "serving"})
        if items:
            call("log_food", {"meal_type": meal or "other", "items": items})
            return calls, "food"

    return calls, "none"


def _f(v: Any, digits: int = 0) -> str:
    try:
        return f"{float(v):.{digits}f}"
    except (TypeError, ValueError):
        return "0"


def _tool_reply(tool_msg: dict) -> str:
    """Human-friendly one-liner after tool execution (mock provider)."""
    name = tool_msg.get("name", "")
    try:
        data = json.loads(tool_msg.get("content") or "{}")
    except json.JSONDecodeError:
        return "Done."
    if "error" in data:
        return f"That didn't work: {data['error']}"
    if name == "log_food":
        logged = data.get("logged", {})
        unmatched = data.get("unmatched") or []
        text = f"Logged {logged.get('meal_type', 'meal')} — {_f(logged.get('calories'))} kcal, {_f(logged.get('protein'))}g protein."
        if unmatched:
            text += f" No nutrition data for: {', '.join(unmatched)} — add them as custom foods for exact numbers."
        return text
    if name == "log_water":
        return f"Logged. Today's total: {_f(data.get('today_total_ml'))} ml."
    if name == "record_measurement":
        r = data.get("recorded", {})
        return f"Recorded {r.get('type', 'measurement')}: {r.get('value')} {r.get('unit', '')}."
    if name == "log_sleep_hours" or name == "log_sleep_times" or name == "log_sleep":
        mins = int(float(data.get("logged", {}).get("duration_min") or 0))
        return f"Sleep logged: {mins // 60}h {mins % 60}m."
    if name == "create_target":
        c = data.get("created", {})
        period_word = {"daily": "day", "weekly": "week", "monthly": "month"}.get(str(c.get("period", "daily")), "day")
        return f"Target set: {c.get('key', '').replace('_', ' ')} {c.get('value')} {c.get('unit', '')} per {period_word}."
    if name == "create_goal":
        return f"Goal created: {data.get('created', {}).get('title', '')}."
    if name == "create_habit":
        return f"Habit created: {data.get('created', {}).get('name', '')}."
    if name == "log_habit_by_name":
        return f"Marked done: {data.get('habit', '')}."
    if name == "log_workout":
        r = data.get("logged", {})
        return f"Workout logged — {r.get('title', '')}, {_f(r.get('total_volume'))} kg volume."
    if name == "create_schedule_event":
        r = data.get("created", {})
        return f"Scheduled: {r.get('title', '')}."
    if name == "get_daily_summary":
        n = data.get("nutrition", {})
        return (f"Today so far: {_f(n.get('calories'))} kcal, {_f(n.get('protein'))}g protein, "
                f"{_f(data.get('water_ml'))}ml water, {data.get('workout_count', 0)} workout(s), "
                f"habits {data.get('habits_completed', 0)}/{data.get('habits_total', 0)}.")
    if name == "get_weight_trend":
        if data.get("points", 0) > 0:
            return (f"Weight: {data.get('latest', {}).get('value')} kg "
                    f"({float(data.get('change') or 0):+.1f} kg over the period, {float(data.get('weekly_rate') or 0):+.2f} kg/week).")
        return "No weight entries yet — log your weight and I'll chart the trend."
    return "Done."


FINAL_REPLIES = {
    "water": "Logged your water intake. Anything else?",
    "weight": "Weight recorded. You'll see it on your progress chart.",
    "sleep": "Sleep logged. Recovery matters as much as training.",
    "target": "Target updated. I'll track your progress against it.",
    "schedule": "Added to your schedule.",
    "goal": "Goal created. You can refine it anytime from the Goals section.",
    "habit": "Habit created. It'll show up on your Today screen.",
    "habit_log": "Habit marked complete. Nice work.",
    "workout": "Workout logged. Volume is calculated automatically.",
    "food": "Logged. Nutrition totals update instantly against your targets.",
    "summary": "Here's where you stand today.",
}


class MockProvider(AIProvider):
    name = "mock"

    async def complete(self, messages: list[dict], tools: list[dict] | None = None) -> ProviderResponse:
        # second pass: tools already ran — produce the final natural-language reply
        if messages and messages[-1].get("role") == "tool":
            trailing = []
            for m in reversed(messages):
                if m.get("role") != "tool":
                    break
                trailing.append(m)
            parts = [_tool_reply(m) for m in reversed(trailing)]
            text = "\n".join(dict.fromkeys(parts))  # dedupe, keep order
            return ProviderResponse(text=text, model="mock")
        last = next((m for m in reversed(messages) if m.get("role") == "user"), None)
        if last is None:
            return ProviderResponse(text="Done.", model="mock")

        calls, hint = _mock_tool_calls(last["content"])
        if calls:
            return ProviderResponse(tool_calls=calls, model="mock")
        if hint == "none":
            return ProviderResponse(
                text=("I'm running in offline/mock mode — I can log things and answer with your data. Try: "
                      "\"log two eggs and 200g rice for lunch\", \"drank 750ml water\", \"weighed 81.3\", "
                      "\"slept 7.5 hours\", \"set protein target to 140\", or \"how am I doing?\"."),
                model="mock")
        return ProviderResponse(text=FINAL_REPLIES.get(hint, "Done."), model="mock")


# ---------------------------------------------------------------------------
# OpenAI-compatible provider: works with OpenAI, Ollama, vLLM, etc.
# ---------------------------------------------------------------------------

class OpenAICompatibleProvider(AIProvider):
    name = "openai_compatible"

    def __init__(self) -> None:
        s = get_settings()
        self.base_url = s.ai_base_url.rstrip("/")
        self.api_key = s.ai_api_key
        self.model = s.ai_model

    async def complete(self, messages: list[dict], tools: list[dict] | None = None) -> ProviderResponse:
        payload: dict[str, Any] = {"model": self.model, "messages": messages}
        if tools:
            payload["tools"] = [
                {"type": "function", "function": {"name": t["name"], "description": t["description"],
                                                  "parameters": t["input_schema"]}}
                for t in tools
            ]
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        async with httpx.AsyncClient(timeout=90) as client:
            resp = await client.post(f"{self.base_url}/chat/completions", json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        choice = data["choices"][0]["message"]
        calls = []
        for tc in choice.get("tool_calls") or []:
            try:
                args = json.loads(tc["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            calls.append(ToolCall(id=tc.get("id", f"call-{len(calls)}"), name=tc["function"]["name"], arguments=args))
        return ProviderResponse(
            text=choice.get("content") or "",
            tool_calls=calls,
            model=data.get("model", self.model),
            usage=data.get("usage") or {},
        )


def get_provider() -> AIProvider:
    settings = get_settings()
    if settings.ai_provider == "openai_compatible" and (settings.ai_api_key or "localhost" in settings.ai_base_url):
        return OpenAICompatibleProvider()
    return MockProvider()
