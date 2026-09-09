"""Track C — plan versioning, device ingest, search."""

import os
import sys
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("AI_PROVIDER", "mock")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.ratelimit import RateLimitMiddleware

API = "/api/v1"


@pytest.fixture(autouse=True)
def _clear_rate_limit():
    # the in-memory limiter is process-global; keep tests independent of each other
    stack = app.middleware_stack or app.build_middleware_stack()
    mw = stack
    while mw is not None:
        if isinstance(mw, RateLimitMiddleware):
            mw._hits.clear()
            break
        mw = getattr(mw, "app", None)


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        async with app.router.lifespan_context(app):
            yield c


async def signup(client, email: str) -> None:
    r = await client.post(f"{API}/auth/signup",
                          json={"email": email, "password": "password123", "name": "C"})
    assert r.status_code == 201, r.text


@pytest.mark.asyncio
async def test_target_change_creates_version_and_revert_restores(client):
    await signup(client, "c-target@example.com")
    r = await client.post(f"{API}/targets", json={"key": "protein", "value": 140, "unit": "g"})
    assert r.status_code == 201
    t1 = r.json()["id"]

    # replacing the target versions the old row before deactivating it
    r = await client.post(f"{API}/targets", json={"key": "protein", "value": 150, "unit": "g"})
    assert r.status_code == 201

    r = await client.get(f"{API}/versions/target/{t1}")
    assert r.status_code == 200
    versions = r.json()
    assert len(versions) == 1
    v1 = versions[0]
    assert v1["version"] == 1 and v1["actor"] == "user"
    assert v1["snapshot"]["value"] == 140 and v1["snapshot"]["active"] is True

    # revert writes the snapshot back through the normal service path
    r = await client.post(f"{API}/versions/{v1['id']}/revert")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["entity"]["value"] == 140 and body["entity"]["active"] is True

    # the revert itself is versioned with the contract reason; the snapshot is
    # t1's pre-revert state (still value=140, but deactivated by the replacement)
    versions = (await client.get(f"{API}/versions/target/{t1}")).json()
    assert len(versions) == 2
    assert versions[0]["reason"] == "revert to v1"  # newest first
    assert versions[0]["snapshot"]["active"] is False


@pytest.mark.asyncio
async def test_goal_and_plan_updates_versioned_and_revertible(client):
    await signup(client, "c-goal@example.com")
    r = await client.post(f"{API}/goals", json={"type": "custom", "title": "TrackC goal"})
    goal_id = r.json()["id"]
    r = await client.patch(f"{API}/goals/{goal_id}", json={"title": "TrackC goal v2"})
    assert r.status_code == 200

    versions = (await client.get(f"{API}/versions/goal/{goal_id}")).json()
    assert len(versions) == 1
    assert versions[0]["snapshot"]["title"] == "TrackC goal"
    assert versions[0]["reason"] == "goal update"

    r = await client.post(f"{API}/versions/{versions[0]['id']}/revert")
    assert r.status_code == 200
    assert r.json()["entity"]["title"] == "TrackC goal"
    assert (await client.get(f"{API}/goals")).json()[0]["title"] == "TrackC goal"

    # workout plan
    r = await client.post(f"{API}/workout-plans", json={"name": "PPL", "days": []})
    plan_id = r.json()["id"]
    r = await client.put(f"{API}/workout-plans/{plan_id}",
                         json={"name": "PPL v2", "days": [{"name": "Push", "exercises": []}]})
    assert r.status_code == 200
    versions = (await client.get(f"{API}/versions/workout_plan/{plan_id}")).json()
    assert len(versions) == 1 and versions[0]["snapshot"]["name"] == "PPL"
    r = await client.post(f"{API}/versions/{versions[0]['id']}/revert")
    assert r.json()["entity"]["name"] == "PPL"

    # unknown entity type / other user's version ids
    assert (await client.get(f"{API}/versions/bogus/{goal_id}")).status_code == 404
    await signup(client, "c-goal2@example.com")
    assert (await client.get(f"{API}/versions/goal/{goal_id}")).json() == []
    assert (await client.post(f"{API}/versions/{versions[0]['id']}/revert")).status_code == 404


@pytest.mark.asyncio
async def test_ai_target_change_records_ai_actor(client):
    await signup(client, "c-ai-actor@example.com")
    r = await client.post(f"{API}/targets", json={"key": "protein", "value": 140, "unit": "g"})
    t1 = r.json()["id"]

    # mock provider parses this into a create_target tool call (source="ai")
    r = await client.post(f"{API}/ai/chat", json={"message": "set protein target to 160"})
    assert r.status_code == 200, r.text
    assert any(a["tool"] == "create_target" and a["status"] == "executed" for a in r.json()["actions"])

    versions = (await client.get(f"{API}/versions/target/{t1}")).json()
    assert len(versions) == 1
    assert versions[0]["actor"] == "ai"
    assert versions[0]["snapshot"]["value"] == 140


@pytest.mark.asyncio
async def test_ingest_token_flow_and_idempotency(client):
    await signup(client, "c-ingest@example.com")

    r = await client.get(f"{API}/integrations/token")
    assert r.status_code == 200
    token = r.json()["token"]
    assert len(token) > 20
    assert (await client.get(f"{API}/integrations/token")).json()["token"] == token  # stable

    r = await client.post(f"{API}/integrations/rotate")
    token2 = r.json()["token"]
    assert token2 != token

    payload = {
        "source": "apple_health",
        "events": [
            {"metric": "weight", "value": 81.2, "unit": "kg",
             "observed_at": "2026-09-08T07:00:00Z", "external_id": "w1"},
            {"metric": "steps", "value": 8500,
             "observed_at": "2026-09-08T22:00:00Z", "external_id": "s1"},
            {"metric": "water_ml", "value": 500,
             "observed_at": "2026-09-08T10:00:00Z", "external_id": "h1"},
            {"metric": "sleep_minutes", "value": 420,
             "observed_at": "2026-09-08T07:05:00Z", "external_id": "sl1"},
            {"metric": "not_a_metric", "value": 1,
             "observed_at": "2026-09-08T07:05:00Z", "external_id": "x1"},
        ],
    }
    auth = {"Authorization": f"Bearer {token2}"}
    r = await client.post(f"{API}/integrations/ingest", json=payload, headers=auth)
    assert r.status_code == 200, r.text
    assert r.json() == {"accepted": 4, "duplicates": 0, "rejected": 1}

    # re-ingest: external_id makes it idempotent
    r = await client.post(f"{API}/integrations/ingest", json=payload, headers=auth)
    assert r.json() == {"accepted": 0, "duplicates": 4, "rejected": 1}

    # mirrors landed in the domain tables
    r = await client.get(f"{API}/measurements", params={"type": "weight"})
    weights = [m for m in r.json() if m["value"] == 81.2]
    assert len(weights) == 1 and weights[0]["source"] == "device" and weights[0]["date"] == "2026-09-08"

    r = await client.get(f"{API}/activities")
    walks = [a for a in r.json() if a["type"] == "walking" and a["steps"] == 8500]
    assert len(walks) == 1 and walks[0]["date"] == "2026-09-08"

    r = await client.get(f"{API}/water", params={"day": "2026-09-08"})
    assert r.json()["total_ml"] == 500

    # sleep stays event-only (no SleepLog rows)
    assert (await client.get(f"{API}/sleep")).json() == []


@pytest.mark.asyncio
async def test_ingest_rejects_wrong_token(client):
    await signup(client, "c-auth@example.com")
    token = (await client.get(f"{API}/integrations/token")).json()["token"]
    payload = {"source": "shortcut",
               "events": [{"metric": "steps", "value": 100, "observed_at": "2026-09-08T00:00:00Z"}]}

    r = await client.post(f"{API}/integrations/ingest", json=payload,
                          headers={"Authorization": "Bearer wrong-token"})
    assert r.status_code == 401
    r = await client.post(f"{API}/integrations/ingest", json=payload)  # cookie is NOT accepted
    assert r.status_code == 401

    # rotated-out token stops working
    await client.post(f"{API}/integrations/rotate")
    r = await client.post(f"{API}/integrations/ingest", json=payload,
                          headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_search_hits(client):
    await signup(client, "c-search@example.com")
    r = await client.post(f"{API}/foods", json={"name": "TrackC kelp noodles", "calories": 20})
    assert r.status_code == 201
    r = await client.post(f"{API}/recipes", json={"name": "TrackC kelp bowl", "servings": 1})
    assert r.status_code == 201
    r = await client.post(f"{API}/ai/chat", json={"message": "trackc kelp planning chat"})
    assert r.status_code == 200

    r = await client.get(f"{API}/search", params={"q": "kelp"})
    assert r.status_code == 200
    body = r.json()
    assert any(f["name"] == "TrackC kelp noodles" for f in body["foods"])
    assert any(r["name"] == "TrackC kelp bowl" for r in body["recipes"])
    assert any("kelp" in c["title"] for c in body["conversations"])

    r = await client.get(f"{API}/search", params={"q": "bench"})
    assert any("Bench" in e["name"] for e in r.json()["exercises"])

    # other users don't see my recipes/conversations
    await signup(client, "c-search2@example.com")
    body = (await client.get(f"{API}/search", params={"q": "kelp"})).json()
    assert body["recipes"] == [] and body["conversations"] == []
    assert body["foods"] == []  # my custom food is mine, not global


@pytest.mark.asyncio
async def test_semantic_search_without_provider_returns_message(client):
    await signup(client, "c-sem@example.com")
    r = await client.get(f"{API}/search/semantic", params={"q": "protein"})
    assert r.status_code == 200
    body = r.json()
    assert body["results"] == []
    assert "embeddings-capable provider" in body["message"]
