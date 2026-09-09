import os
import sys
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("AI_PROVIDER", "mock")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from httpx import ASGITransport, AsyncClient

from app.ai.service import _parse_onboarding_keywords
from app.main import app


def test_keyword_parser_extracts_stats_and_enriches():
    p = _parse_onboarding_keywords(
        "I'm a 25 yo male, 173cm, 82kg. I want to lose fat from 82 to 74 kg, "
        "train four times a week, swim twice a week, vegetarian home-cooked food, work from 10 to 7."
    )
    assert p["profile"]["height_cm"] == 173
    assert p["profile"]["sex"] == "male"
    assert p["profile"]["birth_year"] is not None
    assert p["weight_kg"] == 82.0

    assert p["goals"][0]["type"] == "weight_loss"
    assert p["goals"][0]["start_value"] == 82.0 and p["goals"][0]["target_value"] == 74.0

    keys = {t["key"] for t in p["targets"]}
    assert "workouts" in keys and "swimming" in keys

    suggested = {t["key"]: t for t in p["suggested_targets"]}
    # Mifflin: BMR = 10*82 + 6.25*173 - 5*25 + 5 = 1781.25 → TDEE moderate = 2761 → -500 = 2261
    assert suggested["calories"]["source"] == "calculated"
    assert 2100 < suggested["calories"]["value"] < 2400
    assert suggested["protein"]["value"] == 164  # 2.0 g/kg for weight loss
    assert suggested["water"]["value"] == 2500

    assert p["workout_plan"] is not None
    assert [d["name"] for d in p["workout_plan"]["days"]] == ["Upper A", "Lower A", "Upper B", "Lower B"]


def test_enrich_never_fabricates_stats():
    p = _parse_onboarding_keywords("I want to get stronger and sleep better")
    assert p["weight_kg"] is None
    keys = {t["key"] for t in p["suggested_targets"]}
    assert "calories" not in keys and "protein" not in keys  # no stats → no invented numbers
    assert "water" in keys  # default only


@pytest.mark.asyncio
async def test_onboarding_commit_creates_measurement_and_plan():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        async with app.router.lifespan_context(app):
            await c.post("/api/v1/auth/signup", json={"email": "ob@x.co", "password": "password123", "name": "OB"})
            r = await c.post("/api/v1/ai/onboarding/commit", json={
                "profile": {"height_cm": 173, "birth_year": 2001, "sex": "male", "onboarding_completed": True},
                "weight_kg": 82.0,
                "goals": [{"type": "weight_loss", "title": "Lose fat", "target_value": 74, "unit": "kg"}],
                "targets": [{"key": "calories", "value": 2261, "unit": "kcal", "period": "daily"}],
                "workout_plan": {"name": "4x starter", "days": [
                    {"name": "Upper A", "exercises": [{"name": "Barbell Bench Press", "sets": 3, "reps": 10}]},
                ]},
                "events": [], "habits": [], "memories": [],
            })
            assert r.status_code == 200, r.text
            body = r.json()
            assert len(body["created"]["plans"]) == 1

            m = await c.get("/api/v1/measurements", params={"type": "weight"})
            assert m.json()[0]["value"] == 82.0
            g = await c.get("/api/v1/goals")
            assert g.json()[0]["start_value"] == 82.0  # backfilled from recorded weight
            plans = await c.get("/api/v1/workout-plans")
            assert plans.json()[0]["name"] == "4x starter"

            # redo with replace: old goal archived, old plan stays but new one is created
            r = await c.post("/api/v1/ai/onboarding/commit", json={
                "profile": {"onboarding_completed": True},
                "goals": [{"type": "muscle_gain", "title": "Lean bulk"}],
                "targets": [], "events": [], "habits": [], "memories": [], "replace": True,
            })
            assert r.json()["replaced"]["goals"] == 1
            active = await c.get("/api/v1/goals", params={"status": "active"})
            assert [g["title"] for g in active.json()] == ["Lean bulk"]
