import os
import sys
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("AI_PROVIDER", "mock")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        async with app.router.lifespan_context(app):
            yield c


@pytest.mark.asyncio
async def test_full_core_loop(client):
    api = "/api/v1"
    # signup
    r = await client.post(f"{api}/auth/signup", json={"email": "t@example.com", "password": "password123", "name": "T"})
    assert r.status_code == 201, r.text
    assert r.cookies.get("healthos_session")

    # me
    r = await client.get(f"{api}/users/me")
    assert r.status_code == 200 and r.json()["email"] == "t@example.com"

    # goal + target
    r = await client.post(f"{api}/goals", json={"type": "weight_loss", "title": "Cut", "start_value": 82, "target_value": 74, "unit": "kg"})
    assert r.status_code == 201
    goal_id = r.json()["id"]
    r = await client.post(f"{api}/targets", json={"key": "protein", "value": 140, "unit": "g"})
    assert r.status_code == 201

    # food search finds seeded foods
    r = await client.get(f"{api}/foods/search", params={"q": "rice"})
    assert r.status_code == 200 and any("rice" in f["name"].lower() for f in r.json())
    rice = next(f for f in r.json() if f["name"].lower().startswith("white rice"))

    # log food deterministically (200g cooked white rice = 260 kcal)
    r = await client.post(f"{api}/food-logs", json={
        "meal_type": "lunch",
        "items": [{"food_id": rice["id"], "name": rice["name"], "quantity": 200, "unit": "g"}],
    })
    assert r.status_code == 201, r.text
    assert r.json()["calories"] == 260

    r = await client.get(f"{api}/nutrition/daily")
    assert r.json()["calories"] == 260

    # water + sleep + weight
    r = await client.post(f"{api}/water", json={"amount_ml": 500})
    assert r.status_code == 201
    r = await client.post(f"{api}/measurements", json={"type": "weight", "value": 81.2})
    assert r.status_code == 201
    r = await client.get(f"{api}/analytics/daily")
    assert r.json()["water_ml"] == 500
    assert r.json()["weight"] == 81.2

    # workout volume
    r = await client.post(f"{api}/workout-sessions", json={
        "title": "Push", "exercises": [{"name": "Bench", "sets": [{"weight": 60, "reps": 10}] * 3}]})
    assert r.status_code == 201
    assert r.json()["total_volume"] == 1800

    # habit
    r = await client.post(f"{api}/habits", json={"name": "Meditate"})
    habit_id = r.json()["id"]
    r = await client.post(f"{api}/habits/{habit_id}/logs", json={"status": "completed"})
    assert r.status_code == 201
    r = await client.get(f"{api}/habits-progress")
    assert r.json()[0]["streak"] == 1

    # AI chat (mock provider): natural language logging
    r = await client.post(f"{api}/ai/chat", json={"message": "weighed 80.5"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert any(a["tool"] == "record_measurement" and a["status"] == "executed" for a in body["actions"])

    # goal progress reflects latest weight
    r = await client.get(f"{api}/goals/{goal_id}/progress")
    assert r.json()["current"] == 80.5

    # recipe + grocery list
    r = await client.post(f"{api}/recipes", json={
        "name": "Rice bowl", "servings": 2,
        "ingredients": [{"food_id": rice["id"], "name": rice["name"], "quantity": 200, "unit": "g"}],
        "steps": ["Cook rice"]})
    assert r.status_code == 201
    assert r.json()["nutrition"]["per_serving"]["calories"] == 130

    # ownership isolation: second user sees nothing of the first
    r = await client.post(f"{api}/auth/signup", json={"email": "u2@example.com", "password": "password123"})
    assert r.status_code == 201
    r = await client.get(f"{api}/goals")
    assert r.json() == []


@pytest.mark.asyncio
async def test_auth_required(client):
    r = await AsyncClient(transport=ASGITransport(app=app), base_url="http://test").get("/api/v1/users/me")
    assert r.status_code == 401
