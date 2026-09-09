import json
import os
import sys
from datetime import date
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("AI_PROVIDER", "mock")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.ratelimit import RateLimitMiddleware
from app.services import food_providers
from app.services.food_providers import OpenFoodFactsClient, USDAV2Client

API = "/api/v1"


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        async with app.router.lifespan_context(app):
            yield c


def _reset_rate_limits() -> None:
    """Signup is rate-limited (5/min) per process; clear the in-memory window between tests."""
    mw = app.middleware_stack
    while mw is not None:
        if isinstance(mw, RateLimitMiddleware):
            mw._hits.clear()
        mw = getattr(mw, "app", None)


async def auth(client: AsyncClient) -> AsyncClient:
    _reset_rate_limits()
    r = await client.post(f"{API}/auth/signup",
                          json={"email": "tracka@example.com", "password": "password123", "name": "T"})
    assert r.status_code == 201, r.text
    return client


# ---------- import preview ----------

@pytest.mark.asyncio
async def test_import_preview_measurements_csv(client):
    await auth(client)
    text = (
        "date,type,value,unit\n"
        "2024-05-01,weight,81.2,kg\n"
        "not-a-date,weight,80,kg\n"
        "2024-05-03,weight,-2,kg\n"
        "2024-05-04,body_fat,18.5,%\n"
    )
    r = await client.post(f"{API}/import/preview",
                          json={"kind": "measurements", "format": "csv", "text": text})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 4
    assert body["valid"] == 2
    assert [(e["row"]) for e in body["errors"]] == [2, 3]
    assert body["rows"][0] == {"date": "2024-05-01", "type": "weight", "value": 81.2, "unit": "kg"}
    assert body["rows"][1]["type"] == "body_fat"  # unknown types allowed as custom


@pytest.mark.asyncio
async def test_import_preview_json_workouts(client):
    await auth(client)
    text = json.dumps([
        {"date": "2024-05-02", "title": "Push", "exercise": "Bench", "sets": 3, "reps": 10, "weight": 60},
        {"date": "bad", "exercise": "Squat"},
        {"date": "2024-05-02", "exercise": ""},
    ])
    r = await client.post(f"{API}/import/preview",
                          json={"kind": "workouts", "format": "json", "text": text})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 3
    assert body["valid"] == 1
    assert body["rows"][0]["sets"] == 3
    assert len(body["errors"]) == 2


@pytest.mark.asyncio
async def test_import_preview_rejects_garbage(client):
    await auth(client)
    r = await client.post(f"{API}/import/preview",
                          json={"kind": "food_logs", "format": "json", "text": "{not json"})
    assert r.status_code == 200
    body = r.json()
    assert body["valid"] == 0 and body["errors"][0]["row"] == 0
    r = await client.post(f"{API}/import/preview",
                          json={"kind": "food_logs", "format": "csv", "text": ""})
    assert r.status_code == 422  # empty text rejected by schema


# ---------- import commit ----------

@pytest.mark.asyncio
async def test_import_commit_measurements(client):
    await auth(client)
    day = date.today().isoformat()  # /measurements only serves a recent window
    rows = [
        {"date": day, "type": "weight", "value": 81.2, "unit": "kg"},
        {"date": day, "type": "waist", "value": 88, "unit": "cm"},
        {"date": "nope", "value": 1},  # fails server-side re-validation
    ]
    r = await client.post(f"{API}/import/commit", json={"kind": "measurements", "rows": rows})
    assert r.status_code == 200, r.text
    assert r.json() == {"imported": 2, "skipped": 1}
    r = await client.get(f"{API}/measurements", params={"days": 30})
    got = {(m["type"], m["value"], m["source"]) for m in r.json()}
    assert ("weight", 81.2, "import") in got
    assert ("waist", 88.0, "import") in got


@pytest.mark.asyncio
async def test_import_commit_food_logs_groups_by_date_and_meal(client):
    await auth(client)
    rows = [
        {"date": "2024-06-11", "meal_type": "lunch", "name": "Mystery stew",
         "quantity": 300, "unit": "g", "calories": 450, "protein": 30},
        {"date": "2024-06-11", "meal_type": "lunch", "name": "Bread roll", "calories": 150},
        {"date": "2024-06-11", "meal_type": "dinner", "name": "Soup", "calories": 200},
    ]
    r = await client.post(f"{API}/import/commit", json={"kind": "food_logs", "rows": rows})
    assert r.status_code == 200, r.text
    assert r.json() == {"imported": 3, "skipped": 0}
    r = await client.get(f"{API}/food-logs", params={"day": "2024-06-11"})
    logs = r.json()
    assert len(logs) == 2  # lunch rows merged into one log
    lunch = next(log for log in logs if log["meal_type"] == "lunch")
    assert lunch["source"] == "import"
    assert len(lunch["items"]) == 2
    assert lunch["calories"] == 600
    assert lunch["items"][0]["estimated"] is True


@pytest.mark.asyncio
async def test_import_commit_workouts_groups_by_date_and_title(client):
    await auth(client)
    rows = [
        {"date": "2024-06-12", "title": "Push", "exercise": "Bench", "sets": 3, "reps": 10, "weight": 60},
        {"date": "2024-06-12", "title": "Push", "exercise": "Fly", "sets": 2, "reps": 12, "weight": 15},
        {"date": "2024-06-13", "title": "Pull", "exercise": "Row", "reps": 8, "weight": 50},
    ]
    r = await client.post(f"{API}/import/commit", json={"kind": "workouts", "rows": rows})
    assert r.status_code == 200, r.text
    assert r.json() == {"imported": 3, "skipped": 0}
    r = await client.get(f"{API}/workout-sessions")
    sessions = {s["title"]: s for s in r.json()}
    push = sessions["Push"]
    assert len(push["exercises"]) == 2
    assert push["total_volume"] == 3 * 10 * 60 + 2 * 12 * 15  # 2160
    # reps/weight without sets collapses to a single set
    assert sessions["Pull"]["exercises"][0]["sets"] == [{"weight": 50, "reps": 8}]


# ---------- provider normalization (mocked httpx) ----------

def mock_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_openfoodfacts_search_normalizes_per_100g():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "search.pl" in str(request.url)
        assert request.url.params["search_terms"] == "nutella"
        return httpx.Response(200, json={"products": [
            {"code": "3017620422003", "product_name": "Nutella", "brands": "Ferrero,Nutella",
             "nutriments": {"energy-kcal_100g": 539, "proteins_100g": 6.3,
                            "carbohydrates_100g": 57.5, "fat_100g": 30.9, "fiber_100g": 3.4}},
            {"product_name": ""},  # nameless products are dropped
        ]})

    rows = await OpenFoodFactsClient(client=mock_client(handler)).search("nutella")
    assert rows == [{
        "name": "Nutella", "brand": "Ferrero", "serving_size": 100.0, "serving_unit": "g",
        "calories": 539.0, "protein": 6.3, "carbs": 57.5, "fat": 30.9, "fiber": 3.4,
        "source": "openfoodfacts", "barcode": "3017620422003",
    }]


@pytest.mark.asyncio
async def test_openfoodfacts_barcode_normalizes():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "/api/v2/product/3017620422003.json" in str(request.url)
        return httpx.Response(200, json={"status": 1, "product": {
            "code": "3017620422003", "product_name": "Nutella", "brands": "Ferrero",
            "nutriments": {"energy-kcal_100g": 539}}})

    row = await OpenFoodFactsClient(client=mock_client(handler)).barcode("3017620422003")
    assert row["name"] == "Nutella" and row["barcode"] == "3017620422003"
    assert row["calories"] == 539.0 and row["protein"] == 0.0


@pytest.mark.asyncio
async def test_usda_search_normalizes_per_100g():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["api_key"] == "test-key"
        return httpx.Response(200, json={"foods": [{
            "fdcId": 1, "description": "GREEK YOGURT, PLAIN", "brandOwner": "Fage",
            "gtinUpc": "0689544081001",
            "foodNutrients": [
                {"nutrientId": 1008, "value": 97}, {"nutrientId": 1003, "value": 9},
                {"nutrientId": 1005, "value": 3.9}, {"nutrientId": 1004, "value": 5},
                {"nutrientId": 9999, "value": 123},  # unknown nutrients ignored
            ]}]})

    rows = await USDAV2Client(api_key="test-key", client=mock_client(handler)).search("yogurt")
    assert rows == [{
        "name": "GREEK YOGURT, PLAIN", "brand": "Fage", "serving_size": 100.0, "serving_unit": "g",
        "calories": 97.0, "protein": 9.0, "carbs": 3.9, "fat": 5.0, "fiber": 0.0,
        "source": "usda", "barcode": "0689544081001",
    }]


@pytest.mark.asyncio
async def test_usda_barcode_matches_gtinupc_ignoring_leading_zeros():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"foods": [{
            "description": "GREEK YOGURT, PLAIN", "gtinUpc": "0689544081001",
            "foodNutrients": [{"nutrientId": 1008, "value": 97}]}]})

    row = await USDAV2Client(api_key="k", client=mock_client(handler)).barcode("689544081001")
    assert row["barcode"] == "0689544081001"


@pytest.mark.asyncio
async def test_providers_degrade_gracefully():
    def boom(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "down"})

    def offline(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no network", request=request)

    assert await OpenFoodFactsClient(client=mock_client(boom)).search("x") == []
    assert await OpenFoodFactsClient(client=mock_client(offline)).barcode("1") is None
    assert await USDAV2Client(api_key="k", client=mock_client(offline)).search("x") == []
    # USDA without a key never even tries
    assert await USDAV2Client(api_key="", client=mock_client(boom)).search("x") == []


# ---------- search merge + barcode endpoint ----------

@pytest.mark.asyncio
async def test_search_provider_local_never_calls_remote(client, monkeypatch):
    await auth(client)

    async def fail(*args, **kwargs):
        raise AssertionError("remote must not be called for provider=local")

    monkeypatch.setattr(food_providers, "search_remote", fail)
    r = await client.get(f"{API}/foods/search", params={"q": "rice", "provider": "local"})
    assert r.status_code == 200
    assert any("rice" in f["name"].lower() for f in r.json())


@pytest.mark.asyncio
async def test_search_auto_merges_local_first_and_caches(client, monkeypatch):
    await auth(client)

    async def fake_remote(query, limit=20, providers=None):
        return [{"name": "Remote Rice Cakes", "brand": "SnackCo", "serving_size": 100.0,
                 "serving_unit": "g", "calories": 380.0, "protein": 8.0, "carbs": 80.0,
                 "fat": 3.0, "fiber": 2.0, "source": "usda", "barcode": "0123456789012"}]

    monkeypatch.setattr(food_providers, "search_remote", fake_remote)
    r = await client.get(f"{API}/foods/search", params={"q": "rice", "provider": "auto"})
    assert r.status_code == 200, r.text
    names = [f["name"] for f in r.json()]
    remote = next(f for f in r.json() if f["name"] == "Remote Rice Cakes")
    assert remote["source"] == "usda" and remote["barcode"] == "0123456789012"
    assert names.index("Remote Rice Cakes") > names.index("White rice (cooked)")  # local first
    # cached as a global food: visible to a different user without remote calls
    r = await client.post(f"{API}/auth/signup",
                          json={"email": "tracka8b@example.com", "password": "password123"})
    assert r.status_code == 201
    r = await client.get(f"{API}/foods/search", params={"q": "Remote Rice", "provider": "local"})
    assert any(f["name"] == "Remote Rice Cakes" for f in r.json())


@pytest.mark.asyncio
async def test_barcode_endpoint_found_then_cached(client, monkeypatch):
    await auth(client)
    calls: list[str] = []

    async def fake_remote(code, providers=None):
        calls.append(code)
        return {"name": "Test Bar", "brand": None, "serving_size": 100.0, "serving_unit": "g",
                "calories": 250.0, "protein": 10.0, "carbs": 30.0, "fat": 8.0, "fiber": 2.0,
                "source": "openfoodfacts", "barcode": code}

    monkeypatch.setattr(food_providers, "barcode_remote", fake_remote)
    r = await client.get(f"{API}/foods/barcode/4607025392119")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == "Test Bar"
    assert body["source"] == "openfoodfacts"
    assert body["barcode"] == "4607025392119"
    # second lookup served from the local cache
    r = await client.get(f"{API}/foods/barcode/4607025392119")
    assert r.status_code == 200
    assert calls == ["4607025392119"]


@pytest.mark.asyncio
async def test_barcode_endpoint_404(client, monkeypatch):
    await auth(client)

    async def no_hit(code, providers=None):
        return None

    monkeypatch.setattr(food_providers, "barcode_remote", no_hit)
    r = await client.get(f"{API}/foods/barcode/0000000000000")
    assert r.status_code == 404
    assert r.json() == {"detail": "not found"}
