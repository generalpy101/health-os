"""AI tool registry: strict JSON schemas + handlers that call domain services.

The AI never touches SQL; it calls these tools. Every call is validated,
executed through services, and audited.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Habit, User, UserMemory, UserProfile
from ..schemas import (ActivityIn, EventIn, FoodLogIn, FoodLogItemIn, GoalIn, HabitIn, HabitLogIn,
                       MeasurementIn, SleepIn, TargetIn, WaterIn, WorkoutIn)
from ..services import fitness, goals, habits, health, nutrition, schedule
from ..services import analytics as analytics_service
from ..utils.time import parse_date, user_now, user_today

Handler = Callable[[AsyncSession, User, dict], Awaitable[dict]]

LOW, MEDIUM, HIGH = "low", "medium", "high"


def _s(v: Any) -> Any:
    """Make values JSON-safe."""
    import uuid
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, uuid.UUID):
        return str(v)
    if isinstance(v, dict):
        return {k: _s(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_s(x) for x in v]
    return v


def _obj(o: Any, fields: list[str]) -> dict:
    return {f: _s(getattr(o, f, None)) for f in fields}


# ---------------- handlers ----------------

async def h_get_user_profile(db, user, args):
    profile = (await db.execute(select(UserProfile).where(UserProfile.user_id == user.id))).scalar_one_or_none()
    return {"user": _obj(user, ["name", "timezone", "units"]),
            "profile": _obj(profile, ["height_cm", "birth_year", "sex", "activity_level", "dietary"]) if profile else None}


async def h_get_goals(db, user, args):
    gs = await goals.list_goals(db, user, status_filter=args.get("status") or "active")
    return {"goals": [_obj(g, ["id", "type", "title", "status", "start_value", "target_value", "unit", "target_date"]) for g in gs]}


async def h_create_goal(db, user, args):
    g = await goals.create_goal(db, user, GoalIn(**args), source="ai")
    return {"created": _obj(g, ["id", "type", "title", "target_value", "unit"])}


async def h_update_goal(db, user, args):
    from ..schemas import GoalPatch
    g = await goals.update_goal(db, user, args.pop("goal_id"), GoalPatch(**args), actor="ai")
    return {"updated": _obj(g, ["id", "title", "status", "target_value"])}


async def h_get_targets(db, user, args):
    ts = await goals.list_targets(db, user)
    return {"targets": [_obj(t, ["id", "key", "value", "unit", "period", "mode"]) for t in ts]}


async def h_create_target(db, user, args):
    t = await goals.create_target(db, user, TargetIn(source="ai", **args))
    return {"created": _obj(t, ["id", "key", "value", "unit", "period"])}


async def h_search_food(db, user, args):
    foods = await nutrition.search_foods(db, user, args.get("query", ""), limit=args.get("limit", 10))
    return {"foods": [_obj(f, ["id", "name", "serving_size", "serving_unit", "calories", "protein", "carbs", "fat"]) for f in foods]}


async def h_create_custom_food(db, user, args):
    from ..schemas import FoodIn
    f = await nutrition.create_food(db, user, FoodIn(**args))
    return {"created": _obj(f, ["id", "name", "calories", "protein"])}


async def h_log_food(db, user, args):
    log = await nutrition.log_food(db, user, FoodLogIn(**args), source="ai")
    return {"logged": _obj(log, ["id", "date", "meal_type", "calories", "protein"]),
            "items": log.items,
            "unmatched": [i["name"] for i in log.items if i.get("unmatched")]}


async def h_get_daily_nutrition(db, user, args):
    day = parse_date(args.get("date"), user.timezone)
    totals = await nutrition.daily_totals(db, user, day)
    return totals


async def h_log_water(db, user, args):
    log = await health.log_water(db, user, WaterIn(**args))
    total = await health.water_total(db, user, log.date)
    return {"logged_ml": log.amount_ml, "date": _s(log.date), "today_total_ml": total}


async def h_log_sleep_hours(db, user, args):
    hours = float(args["hours"])
    now = user_now(user.timezone)
    end = now.replace(hour=9, minute=0, second=0, microsecond=0)
    if end > now:
        end -= timedelta(days=1)
    start = end - timedelta(hours=hours)
    log = await health.log_sleep(db, user, SleepIn(sleep_start=start, sleep_end=end), source="ai")
    return {"logged": _obj(log, ["id", "date", "duration_min"])}


async def h_log_sleep_times(db, user, args):
    today = user_today(user.timezone)
    sh, sm = map(int, args["start"].split(":"))
    eh, em = map(int, args["end"].split(":"))
    end = datetime.combine(today, datetime.min.time(), tzinfo=user_now(user.timezone).tzinfo).replace(hour=eh, minute=em)
    start = end.replace(hour=sh, minute=sm)
    if start >= end:
        start -= timedelta(days=1)
    log = await health.log_sleep(db, user, SleepIn(sleep_start=start, sleep_end=end), source="ai")
    return {"logged": _obj(log, ["id", "date", "duration_min"])}


async def h_log_sleep(db, user, args):
    log = await health.log_sleep(db, user, SleepIn(**args), source="ai")
    return {"logged": _obj(log, ["id", "date", "duration_min"])}


async def h_record_measurement(db, user, args):
    m = await health.record_measurement(db, user, MeasurementIn(**args), source="ai")
    return {"recorded": _obj(m, ["id", "type", "value", "unit", "date"])}


async def h_get_weight_trend(db, user, args):
    days = int(args.get("days", 30))
    end = user_today(user.timezone)
    trend = await health.weight_trend(db, user, end - timedelta(days=days), end)
    pts = trend["points"]
    out = {"weekly_rate": trend["weekly_rate"], "points": len(pts)}
    if pts:
        out["first"], out["latest"] = pts[0], pts[-1]
        out["change"] = round(pts[-1]["value"] - pts[0]["value"], 2)
    return out


async def h_create_habit(db, user, args):
    h = await habits.create_habit(db, user, HabitIn(**args), source="ai")
    return {"created": _obj(h, ["id", "name", "frequency"])}


async def h_log_habit(db, user, args):
    log = await habits.log_habit(db, user, args.pop("habit_id"), HabitLogIn(**args))
    return {"logged": _obj(log, ["habit_id", "date", "status"])}


async def h_log_habit_by_name(db, user, args):
    name = args["name"].lower()
    all_habits = await habits.list_habits(db, user)
    match = next((h for h in all_habits if name in h.name.lower() or h.name.lower() in name), None)
    if match is None:
        h = await habits.create_habit(db, user, HabitIn(name=args["name"].strip().capitalize()), source="ai")
        match = h
    log = await habits.log_habit(db, user, match.id, HabitLogIn(status="completed"))
    return {"logged": _obj(log, ["habit_id", "date", "status"]), "habit": match.name}


async def h_get_habit_progress(db, user, args):
    return {"habits": await habits.habit_progress(db, user, days=int(args.get("days", 7)))}


async def h_search_exercises(db, user, args):
    exs = await fitness.search_exercises(db, args.get("query", ""), limit=args.get("limit", 10))
    return {"exercises": [_obj(e, ["id", "name", "muscle_groups", "equipment"]) for e in exs]}


async def h_log_workout(db, user, args):
    w = await fitness.log_workout(db, user, WorkoutIn(**args), source="ai")
    return {"logged": _obj(w, ["id", "date", "title", "total_volume"])}


async def h_get_workout_history(db, user, args):
    ws = await fitness.list_workouts(db, user, limit=int(args.get("limit", 10)))
    return {"workouts": [_obj(w, ["id", "date", "title", "duration_min", "total_volume"]) for w in ws]}


async def h_log_activity(db, user, args):
    a = await fitness.log_activity(db, user, ActivityIn(**args), source="ai")
    return {"logged": _obj(a, ["id", "type", "date", "duration_min", "distance_m", "steps"])}


async def h_get_schedule(db, user, args):
    start = parse_date(args.get("start"), user.timezone)
    end = parse_date(args.get("end"), user.timezone) if args.get("end") else start + timedelta(days=6)
    return {"events": [{**e, "start_at": _s(e["start_at"]), "end_at": _s(e["end_at"])}
                       for e in await schedule.get_schedule(db, user, start, end)]}


async def h_create_schedule_event(db, user, args):
    args = dict(args)
    tz = user_now(user.timezone).tzinfo
    today = user_today(user.timezone)
    if "bydays" in args and "start_at" not in args:
        days = sorted(args.pop("bydays"))
        hour = int(args.pop("hour", 18)); minute = int(args.pop("minute", 0))
        d = today
        while d.weekday() not in days:
            d += timedelta(days=1)
        start = datetime.combine(d, datetime.min.time(), tzinfo=tz).replace(hour=hour, minute=minute)
        args["start_at"] = start
        args["recurrence"] = {"freq": "weekly", "bydays": days}
    elif "times_per_week" in args and "start_at" not in args:
        tpw = int(args.pop("times_per_week"))
        start = datetime.combine(today, datetime.min.time(), tzinfo=tz).replace(hour=int(args.pop("hour", 18)))
        args["start_at"] = start
        args["recurrence"] = {"freq": "weekly", "bydays": sorted({(today.weekday() + 2 * i) % 7 for i in range(tpw)})}
    elif "start_at" not in args:
        args["start_at"] = user_now(user.timezone).replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    e = await schedule.create_event(db, user, EventIn(**args), source="ai")
    return {"created": _obj(e, ["id", "title", "type", "start_at", "recurrence"])}


async def h_update_schedule_event(db, user, args):
    from ..schemas import EventPatch
    e = await schedule.update_event(db, user, args.pop("event_id"), EventPatch(**args), source="ai")
    return {"updated": _obj(e, ["id", "title", "start_at", "status"])}


async def h_find_free_time(db, user, args):
    day = parse_date(args.get("date"), user.timezone)
    slots = await schedule.find_free_slots(db, user, day, duration_min=int(args.get("duration_min", 60)))
    return {"date": _s(day), "free_slots": [{k: _s(v) for k, v in s.items()} for s in slots]}


async def h_get_daily_summary(db, user, args):
    return await analytics_service.daily_summary(db, user, parse_date(args.get("date"), user.timezone) if args.get("date") else None)


async def h_get_weekly_summary(db, user, args):
    return await analytics_service.weekly_summary(db, user)


async def h_create_memory(db, user, args):
    mem = UserMemory(user_id=user.id, type=args.get("type", "preference"), key=args["key"],
                     value={"value": args.get("value")}, source="ai",
                     confidence=float(args.get("confidence", 0.7)), status="active")
    db.add(mem)
    await db.commit()
    return {"created": _obj(mem, ["id", "type", "key", "value"])}


async def h_search_recipes(db, user, args):
    from ..services import recipes as recipes_service
    rs = await recipes_service.list_recipes(db, user, args.get("query", ""), limit=int(args.get("limit", 8)))
    return {"recipes": [{"id": str(r.id), "name": r.name, "servings": r.servings,
                         "per_serving": (r.nutrition or {}).get("per_serving", {}),
                         "tags": r.tags, "cuisine": r.cuisine} for r in rs]}


async def h_create_recipe(db, user, args):
    from ..schemas import RecipeIn
    from ..services import recipes as recipes_service
    r = await recipes_service.create_recipe(db, user, RecipeIn(**args), source="ai")
    return {"created": {"id": str(r.id), "name": r.name, "servings": r.servings,
                        "nutrition_per_serving": (r.nutrition or {}).get("per_serving", {})}}


async def h_update_recipe(db, user, args):
    from ..schemas import RecipeIn
    from ..services import recipes as recipes_service
    r = await recipes_service.update_recipe(db, user, args.pop("recipe_id"), RecipeIn(**args))
    return {"updated": {"id": str(r.id), "name": r.name,
                        "nutrition_per_serving": (r.nutrition or {}).get("per_serving", {})}}


async def h_delete_recipe(db, user, args):
    from ..services import recipes as recipes_service
    await recipes_service.delete_recipe(db, user, args["recipe_id"])
    return {"deleted": True}


async def h_suggest_meal(db, user, args):
    from ..services import suggest as suggest_service
    return await suggest_service.meal_suggestions(db, user)


async def h_get_user_memories(db, user, args):
    result = await db.execute(
        select(UserMemory).where(UserMemory.user_id == user.id, UserMemory.status == "active")
        .order_by(UserMemory.updated_at.desc()).limit(int(args.get("limit", 20)))
    )
    return {"memories": [_obj(m, ["id", "type", "key", "value", "source", "confidence"]) for m in result.scalars().all()]}


# ---------------- registry ----------------

def _schema(name: str, description: str, properties: dict, required: list[str] | None = None) -> dict:
    return {"name": name, "description": description,
            "input_schema": {"type": "object", "properties": properties, "required": required or []}}


S = {"type": "string"}
N = {"type": "number"}

REGISTRY: dict[str, tuple[dict, Handler, str]] = {
    "get_user_profile": (_schema("get_user_profile", "Get the user's profile, units and dietary info", {}), h_get_user_profile, LOW),
    "get_goals": (_schema("get_goals", "List goals", {"status": S}), h_get_goals, LOW),
    "create_goal": (_schema("create_goal", "Create a goal", {
        "type": S, "title": S, "start_value": N, "target_value": N, "unit": S, "target_date": S},
        ["type", "title"]), h_create_goal, MEDIUM),
    "update_goal": (_schema("update_goal", "Update a goal", {
        "goal_id": S, "title": S, "status": S, "target_value": N, "unit": S}, ["goal_id"]), h_update_goal, MEDIUM),
    "get_targets": (_schema("get_targets", "List active daily/weekly targets", {}), h_get_targets, LOW),
    "create_target": (_schema("create_target", "Set or replace a target (calories, protein, water, steps, sleep_minutes, workouts...)", {
        "key": S, "value": N, "unit": S, "period": S, "mode": S, "reason": S}, ["key", "value", "unit"]), h_create_target, MEDIUM),
    "search_food": (_schema("search_food", "Search the food database", {"query": S, "limit": N}), h_search_food, LOW),
    "create_custom_food": (_schema("create_custom_food", "Create a custom food with nutrients per serving", {
        "name": S, "serving_size": N, "serving_unit": S, "calories": N, "protein": N, "carbs": N, "fat": N},
        ["name", "calories"]), h_create_custom_food, LOW),
    "log_food": (_schema("log_food", "Log food items for a meal. Units: g/ml/kg/l/oz/cup/tbsp/tsp, or piece/scoop/serving. When the user states nutrients explicitly (e.g. 'my scoop has 24g protein'), pass calories/protein on that item — explicit values beat database lookup.", {
        "date": S, "meal_type": S, "note": S,
        "items": {"type": "array", "items": {"type": "object", "properties": {
            "food_id": S, "name": S, "quantity": N, "unit": S,
            "calories": N, "protein": N, "carbs": N, "fat": N}, "required": ["name", "quantity"]}}},
        ["items"]), h_log_food, LOW),
    "get_daily_nutrition": (_schema("get_daily_nutrition", "Get deterministic nutrition totals for a day", {"date": S}), h_get_daily_nutrition, LOW),
    "log_water": (_schema("log_water", "Log water intake in ml", {"amount_ml": N, "date": S}, ["amount_ml"]), h_log_water, LOW),
    "log_sleep_hours": (_schema("log_sleep_hours", "Log sleep by duration in hours", {"hours": N}, ["hours"]), h_log_sleep_hours, LOW),
    "log_sleep_times": (_schema("log_sleep_times", "Log sleep by HH:MM start and end times", {"start": S, "end": S}, ["start", "end"]), h_log_sleep_times, LOW),
    "log_sleep": (_schema("log_sleep", "Log sleep with ISO datetimes", {
        "sleep_start": S, "sleep_end": S, "quality": N}, ["sleep_start", "sleep_end"]), h_log_sleep, LOW),
    "record_measurement": (_schema("record_measurement", "Record a body measurement", {
        "type": S, "value": N, "unit": S, "date": S}, ["type", "value"]), h_record_measurement, LOW),
    "get_weight_trend": (_schema("get_weight_trend", "Get weight trend with weekly rate of change", {"days": N}), h_get_weight_trend, LOW),
    "create_habit": (_schema("create_habit", "Create a habit", {
        "name": S, "frequency": S, "target": N, "unit": S}, ["name"]), h_create_habit, LOW),
    "log_habit": (_schema("log_habit", "Log habit completion", {
        "habit_id": S, "status": S, "value": N, "date": S}, ["habit_id"]), h_log_habit, LOW),
    "log_habit_by_name": (_schema("log_habit_by_name", "Log habit completion by habit name (creates it if missing)", {
        "name": S}, ["name"]), h_log_habit_by_name, LOW),
    "get_habit_progress": (_schema("get_habit_progress", "Habit adherence and streaks", {"days": N}), h_get_habit_progress, LOW),
    "search_exercises": (_schema("search_exercises", "Search the exercise database", {"query": S, "limit": N}), h_search_exercises, LOW),
    "log_workout": (_schema("log_workout", "Log a workout session", {
        "date": S, "title": S, "duration_min": N,
        "exercises": {"type": "array", "items": {"type": "object", "properties": {
            "name": S, "sets": {"type": "array", "items": {"type": "object", "properties": {
                "weight": N, "reps": N, "rpe": N, "duration_s": N, "distance_m": N}}}}, "required": ["name"]}}},
        ["title"]), h_log_workout, LOW),
    "get_workout_history": (_schema("get_workout_history", "Recent workout sessions", {"limit": N}), h_get_workout_history, LOW),
    "log_activity": (_schema("log_activity", "Log an activity (walking, running, swimming...)", {
        "type": S, "date": S, "duration_min": N, "distance_m": N, "steps": N, "intensity": S, "notes": S},
        ["type"]), h_log_activity, LOW),
    "get_schedule": (_schema("get_schedule", "Get schedule events in a date range", {"start": S, "end": S}), h_get_schedule, LOW),
    "create_schedule_event": (_schema("create_schedule_event", "Create a schedule event (supports recurrence)", {
        "type": S, "title": S, "start_at": S, "end_at": S, "recurrence": {"type": "object"}},
        ["title"]), h_create_schedule_event, MEDIUM),
    "update_schedule_event": (_schema("update_schedule_event", "Move or update a schedule event", {
        "event_id": S, "title": S, "start_at": S, "end_at": S, "status": S}, ["event_id"]), h_update_schedule_event, MEDIUM),
    "find_free_time": (_schema("find_free_time", "Find free time slots on a day", {"date": S, "duration_min": N}), h_find_free_time, LOW),
    "get_daily_summary": (_schema("get_daily_summary", "Full daily summary: nutrition, water, sleep, workouts, habits, schedule", {"date": S}), h_get_daily_summary, LOW),
    "get_weekly_summary": (_schema("get_weekly_summary", "Weekly adherence and trend summary", {}), h_get_weekly_summary, LOW),
    "create_memory": (_schema("create_memory", "Remember a user preference or fact", {
        "type": S, "key": S, "value": S, "confidence": N}, ["key", "value"]), h_create_memory, LOW),
    "get_user_memories": (_schema("get_user_memories", "Retrieve remembered preferences/facts", {"limit": N}), h_get_user_memories, LOW),
    "suggest_meal": (_schema("suggest_meal", "Rank the user's recipes/saved meals against what's left of today's targets (use for 'what should I eat')", {}), h_suggest_meal, LOW),
    "search_recipes": (_schema("search_recipes", "Search the user's recipes", {"query": S, "limit": N}), h_search_recipes, LOW),
    "create_recipe": (_schema("create_recipe", "Create a recipe; nutrition per serving is computed by the system from ingredients", {
        "name": S, "description": S, "servings": N, "prep_minutes": N, "cook_minutes": N, "cuisine": S,
        "tags": {"type": "array", "items": S}, "steps": {"type": "array", "items": S},
        "ingredients": {"type": "array", "items": {"type": "object", "properties": {
            "food_id": S, "name": S, "quantity": N, "unit": S}, "required": ["name", "quantity"]}}},
        ["name", "ingredients"]), h_create_recipe, LOW),
    "update_recipe": (_schema("update_recipe", "Update a recipe in place (never create a duplicate to 'fix' one)", {
        "recipe_id": S, "name": S, "description": S, "servings": N, "prep_minutes": N, "cook_minutes": N,
        "cuisine": S, "tags": {"type": "array", "items": S}, "steps": {"type": "array", "items": S},
        "ingredients": {"type": "array", "items": {"type": "object", "properties": {
            "food_id": S, "name": S, "quantity": N, "unit": S}, "required": ["name", "quantity"]}}},
        ["recipe_id", "name", "ingredients"]), h_update_recipe, MEDIUM),
    "delete_recipe": (_schema("delete_recipe", "Delete a recipe", {"recipe_id": S}, ["recipe_id"]), h_delete_recipe, HIGH),
}


def tool_schemas() -> list[dict]:
    return [schema for schema, _, _ in REGISTRY.values()]


async def execute_tool(db: AsyncSession, user: User, name: str, arguments: dict) -> dict:
    if name not in REGISTRY:
        return {"error": f"unknown tool: {name}"}
    _, handler, _ = REGISTRY[name]
    try:
        return await handler(db, user, dict(arguments))
    except Exception as exc:  # never let one tool crash the chat
        return {"error": f"{type(exc).__name__}: {exc}"}
