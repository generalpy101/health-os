"""Track D: saved meals, frequent foods, PRs, activity calendar, stall detector, pantry."""

import itertools
import os
import sys
from datetime import date, timedelta
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("AI_PROVIDER", "mock")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.db import SessionLocal
from app.main import app
from app.models import AuditLog

_hosts = itertools.count()


@pytest.fixture
async def client():
    # distinct client host per test -> own rate-limit bucket (signup is limited to 5/min)
    n = next(_hosts)
    transport = ASGITransport(app=app, client=(f"10.77.{n // 256}.{n % 256}", 9999))
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        async with app.router.lifespan_context(app):
            yield c


async def _auth(client: AsyncClient, email: str = "trackd@example.com") -> None:
    r = await client.post("/api/v1/auth/signup", json={"email": email, "password": "password123", "name": "T"})
    assert r.status_code == 201, r.text


async def _server_today(client: AsyncClient) -> str:
    """The user-local 'today' the API computes (avoids test-runner timezone drift)."""
    r = await client.get("/api/v1/analytics/activity-calendar", params={"days": 1})
    assert r.status_code == 200, r.text
    return r.json()[0]["date"]


async def _food_id(client: AsyncClient, name: str) -> str:
    r = await client.get("/api/v1/foods/search", params={"q": name.split(" (")[0]})
    assert r.status_code == 200, r.text
    return next(f["id"] for f in r.json() if f["name"] == name)


# ---------- saved meals & frequent foods ----------

@pytest.mark.asyncio
async def test_saved_meal_log_increments_and_snapshots(client):
    api = "/api/v1"
    await _auth(client)
    rice_id = await _food_id(client, "White rice (cooked)")

    # a manual log to snapshot from (200g white rice = 260 kcal, 5.4g protein)
    r = await client.post(f"{api}/food-logs", json={
        "meal_type": "lunch",
        "items": [{"food_id": rice_id, "name": "White rice (cooked)", "quantity": 200, "unit": "g"}]})
    assert r.status_code == 201, r.text
    log_id = r.json()["id"]

    # save from the log -> stores the resolved snapshot
    r = await client.post(f"{api}/saved-meals", json={"name": "Rice lunch", "from_log_id": log_id})
    assert r.status_code == 201, r.text
    meal = r.json()
    assert meal["use_count"] == 0 and meal["last_used_at"] is None
    assert meal["items"][0]["calories"] == 260 and meal["items"][0]["food_id"] == rice_id

    # logging it twice goes through nutrition.log_food and bumps the counters
    for meal_type in ("lunch", "dinner"):
        r = await client.post(f"{api}/saved-meals/{meal['id']}/log", json={"meal_type": meal_type})
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["source"] == "saved_meal" and body["meal_type"] == meal_type
        assert body["calories"] == 260 and body["protein"] == 5.4
        assert body["items"][0]["food_id"] == rice_id

    r = await client.get(f"{api}/saved-meals")
    [meal] = r.json()
    assert meal["use_count"] == 2 and meal["last_used_at"]

    # create from raw items (resolved via the food db) + delete
    r = await client.post(f"{api}/saved-meals", json={
        "name": "Egg snack", "items": [{"name": "Egg", "quantity": 2, "unit": "piece"}]})
    assert r.status_code == 201, r.text
    egg = r.json()
    assert egg["items"][0]["calories"] == 156 and egg["items"][0]["food_id"]
    r = await client.delete(f"{api}/saved-meals/{egg['id']}")
    assert r.status_code == 204
    r = await client.get(f"{api}/saved-meals")
    assert [m["name"] for m in r.json()] == ["Rice lunch"]

    # rice was logged 3x in the last 60d -> top frequent food, per-serving macros
    r = await client.get(f"{api}/foods/frequent")
    assert r.status_code == 200, r.text
    top = r.json()[0]
    assert top["food_id"] == rice_id and top["name"] == "White rice (cooked)"
    assert top["uses"] == 3 and top["calories"] == 130 and top["protein"] == 2.7


# ---------- PRs ----------

@pytest.mark.asyncio
async def test_pr_detection_across_sessions(client):
    api = "/api/v1"
    await _auth(client)
    today = await _server_today(client)
    d2 = (date.fromisoformat(today) - timedelta(days=2)).isoformat()
    d1 = (date.fromisoformat(today) - timedelta(days=1)).isoformat()

    # first session: both weight and volume PRs (no previous)
    r = await client.post(f"{api}/workout-sessions", json={
        "title": "Push", "date": d2,
        "exercises": [{"name": "Bench", "sets": [{"weight": 60, "reps": 10}] * 3}]})
    assert r.status_code == 201, r.text
    first = r.json()["new_prs"]
    assert {p["kind"] for p in first} == {"weight", "volume"}
    assert next(p for p in first if p["kind"] == "weight")["previous"] is None

    # heavier second session: weight PR with previous; 62.5x5=312.5 < 600 volume -> no volume PR
    r = await client.post(f"{api}/workout-sessions", json={
        "title": "Push", "date": d1,
        "exercises": [{"name": "Bench", "sets": [{"weight": 62.5, "reps": 5}]}]})
    prs = r.json()["new_prs"]
    assert [p for p in prs if p["kind"] == "weight"] == [
        {"exercise": "Bench", "kind": "weight", "value": 62.5, "previous": 60.0}]
    assert not [p for p in prs if p["kind"] == "volume"]

    # lighter third session -> no PRs
    r = await client.post(f"{api}/workout-sessions", json={
        "title": "Push", "date": today,
        "exercises": [{"name": "Bench", "sets": [{"weight": 60, "reps": 8}]}]})
    assert r.json()["new_prs"] == []

    r = await client.get(f"{api}/workouts/prs")
    assert r.status_code == 200, r.text
    [bench] = [p for p in r.json() if p["exercise"] == "Bench"]
    assert bench["best_weight"] == 62.5 and bench["reps_at_best"] == 5
    assert bench["best_volume_set"] == 600 and bench["date"] == d1
    assert bench["is_recent"] is False  # best was set before the latest session

    # audit trail: workout_pr written exactly for the two PR-setting sessions
    async with SessionLocal() as db:
        rows = (await db.execute(select(AuditLog).where(AuditLog.event == "workout_pr"))).scalars().all()
    assert len(rows) == 2 and rows[1].data["prs"][0]["value"] == 62.5


# ---------- activity calendar ----------

@pytest.mark.asyncio
async def test_activity_calendar_scoring_boundaries(client):
    api = "/api/v1"
    await _auth(client)

    days = (await client.get(f"{api}/analytics/activity-calendar", params={"days": 7})).json()
    assert len(days) == 7 and all(d["score"] == 0 for d in days)
    assert all(d["habits_total"] == 0 for d in days)
    today = days[-1]["date"]

    # food only -> light (1); adding a workout -> medium (2)
    # (with no habits configured the habit rungs are False, so 3 is unreachable)
    await client.post(f"{api}/food-logs", json={
        "date": today, "meal_type": "lunch",
        "items": [{"name": "Rice", "quantity": 100, "unit": "g", "calories": 130}]})
    days = (await client.get(f"{api}/analytics/activity-calendar", params={"days": 7})).json()
    assert days[-1]["score"] == 1 and days[-1]["logged_food"] is True

    await client.post(f"{api}/workout-sessions", json={
        "date": today, "title": "W", "exercises": [{"name": "Row", "sets": [{"weight": 40, "reps": 8}]}]})
    days = (await client.get(f"{api}/analytics/activity-calendar", params={"days": 7})).json()
    assert days[-1] == {"date": today, "workouts": 1, "habits_done": 0, "habits_total": 0,
                        "logged_food": True, "score": 2}

    # workout + food + all habits done -> full (3)
    r = await client.post(f"{api}/habits", json={"name": "Meditate"})
    habit_id = r.json()["id"]
    await client.post(f"{api}/habits/{habit_id}/logs", json={"date": today, "status": "completed"})
    days = (await client.get(f"{api}/analytics/activity-calendar", params={"days": 7})).json()
    assert days[-1]["score"] == 3 and days[-1]["habits_done"] == 1 and days[-1]["habits_total"] == 1

    # habits only (yesterday) -> light (1)
    yesterday = days[-2]["date"]
    await client.post(f"{api}/habits/{habit_id}/logs", json={"date": yesterday, "status": "completed"})
    days = (await client.get(f"{api}/analytics/activity-calendar", params={"days": 7})).json()
    assert days[-2]["score"] == 1 and days[-2]["logged_food"] is False


# ---------- stall detector ----------

async def _log_weights(client, today: str, values: list[float]) -> None:
    end = date.fromisoformat(today)
    for i, v in enumerate(values):
        day = end - timedelta(days=len(values) - 1 - i)
        r = await client.post("/api/v1/measurements",
                              json={"type": "weight", "value": v, "date": day.isoformat()})
        assert r.status_code == 201, r.text


@pytest.mark.asyncio
async def test_stall_detector_applies_and_stalled(client):
    api = "/api/v1"
    await _auth(client)

    r = await client.get(f"{api}/insights/stall")
    assert r.status_code == 200, r.text
    assert r.json()["applies"] is False  # no weight goal

    await client.post(f"{api}/goals", json={"type": "weight_loss", "title": "Cut",
                                            "start_value": 82, "target_value": 74, "unit": "kg"})
    r = await client.get(f"{api}/insights/stall")
    assert r.json()["applies"] is False  # <14 days of weight data

    today = await _server_today(client)
    await _log_weights(client, today, [80.0] * 14)  # perfectly flat
    body = (await client.get(f"{api}/insights/stall")).json()
    assert body["applies"] is True and body["stalled"] is True
    assert body["weekly_rate"] == 0.0 and body["weeks_tracked"] == 2.0
    assert len(body["factors"]) == 4
    verdicts = {f["label"]: f["verdict"] for f in body["factors"]}
    # no targets and nothing logged -> adherence factors are the weak links
    assert verdicts == {"Calories": "low", "Protein": "low", "Workouts": "ok", "Sleep": "ok"}
    assert "flat" in body["suggestion"].lower() and "Calories" in body["suggestion"]


@pytest.mark.asyncio
async def test_stall_detector_not_stalled_when_progressing(client):
    api = "/api/v1"
    await _auth(client)
    await client.post(f"{api}/goals", json={"type": "weight_loss", "title": "Cut",
                                            "start_value": 84, "target_value": 74, "unit": "kg"})
    today = await _server_today(client)
    # ~1 kg/week decline over 14 days
    await _log_weights(client, today, [round(84 - 0.14 * i, 2) for i in range(14)])
    body = (await client.get(f"{api}/insights/stall")).json()
    assert body["applies"] is True and body["stalled"] is False
    assert body["weekly_rate"] < -0.05
    assert "no stall" in body["suggestion"].lower()


# ---------- pantry ----------

@pytest.mark.asyncio
async def test_pantry_matches_and_grocery_purchase(client):
    api = "/api/v1"
    await _auth(client)
    today = await _server_today(client)

    r = await client.post(f"{api}/pantry", json={
        "name": "Chicken breast (cooked)", "quantity": 150, "unit": "g", "location": "fridge"})
    assert r.status_code == 201, r.text
    chicken = r.json()
    assert chicken["location"] == "fridge" and chicken["expires_on"] is None
    r = await client.patch(f"{api}/pantry/{chicken['id']}", json={"quantity": 150.0})
    assert r.status_code == 200 and r.json()["quantity"] == 150

    chicken_id = await _food_id(client, "Chicken breast (cooked)")
    rice_id = await _food_id(client, "White rice (cooked)")
    r = await client.post(f"{api}/recipes", json={
        "name": "Chicken rice bowl", "servings": 2,
        "ingredients": [
            {"food_id": chicken_id, "name": "Chicken breast (cooked)", "quantity": 300, "unit": "g"},
            {"food_id": rice_id, "name": "White rice (cooked)", "quantity": 400, "unit": "g"},
        ],
        "steps": ["Cook"]})
    assert r.status_code == 201, r.text
    recipe_id = r.json()["id"]

    # chicken covered (exact name), rice missing -> 0.5
    r = await client.get(f"{api}/pantry/recipe-matches")
    [match] = r.json()
    assert match["recipe_id"] == recipe_id and match["coverage"] == 0.5
    assert match["missing"] == ["White rice (cooked)"]

    # substring match: pantry 'rice' covers 'White rice (cooked)'
    r = await client.post(f"{api}/pantry", json={"name": "Rice", "quantity": 1, "unit": "kg"})
    assert r.status_code == 201
    rice_pantry_id = r.json()["id"]
    r = await client.get(f"{api}/pantry/recipe-matches")
    assert r.json()[0]["coverage"] == 1.0 and r.json()[0]["missing"] == []

    # plan the recipe (2 servings = whole recipe) and buy the groceries
    r = await client.post(f"{api}/meal-plans", json={
        "date": today, "meal_type": "dinner", "recipe_id": recipe_id,
        "name": "Chicken rice bowl", "servings": 2})
    assert r.status_code == 201, r.text
    r = await client.post(f"{api}/grocery-list/purchase", json={"start": today, "end": today})
    assert r.status_code == 200 and r.json() == {"added": 2}

    pantry = (await client.get(f"{api}/pantry")).json()
    by_name = {p["name"].lower(): p for p in pantry}
    assert by_name["chicken breast (cooked)"]["quantity"] == 450  # 150 + 300, upserted
    assert by_name["white rice (cooked)"]["quantity"] == 400      # new row
    assert by_name["rice"]["quantity"] == 1                       # untouched (different key)

    # purchasing again accumulates quantities without duplicating rows
    r = await client.post(f"{api}/grocery-list/purchase", json={"start": today, "end": today})
    assert r.json() == {"added": 2}
    pantry2 = (await client.get(f"{api}/pantry")).json()
    assert len(pantry2) == len(pantry)
    assert {p["name"].lower(): p for p in pantry2}["chicken breast (cooked)"]["quantity"] == 750

    r = await client.delete(f"{api}/pantry/{rice_pantry_id}")
    assert r.status_code == 204
    names = {p["name"].lower() for p in (await client.get(f"{api}/pantry")).json()}
    assert "rice" not in names
