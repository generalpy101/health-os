"""External food data providers (OpenFoodFacts, USDA FoodData Central).

All remote calls are best-effort: any failure (network, timeout, bad payload)
returns no results, so local data is never blocked on a remote outage.
Nutrients are normalized to per-100g.
"""

from __future__ import annotations

import asyncio
from typing import Any, Protocol

import httpx

TIMEOUT = httpx.Timeout(4.0)
HEADERS = {"User-Agent": "HealthOS/0.3 (self-hosted nutrition lookup)"}

OFF_SEARCH_URL = "https://world.openfoodfacts.org/cgi/search.pl"
OFF_PRODUCT_URL = "https://world.openfoodfacts.org/api/v2/product/{code}.json"
USDA_SEARCH_URL = "https://api.nal.usda.gov/fdc/v1/foods/search"

# FDC nutrient id -> our field (values are already per 100g in search results)
USDA_NUTRIENT_IDS = {1008: "calories", 1003: "protein", 1005: "carbs", 1004: "fat", 1079: "fiber"}


def _num(value: Any) -> float:
    """Coerce a remote nutrient value to a finite float, defaulting to 0."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    if v != v or v in (float("inf"), float("-inf")):  # NaN / inf guard
        return 0.0
    return round(max(v, 0.0), 2)


def _normalized(name: str, brand: str | None, nutrients: dict[str, float],
                source: str, barcode: str | None) -> dict:
    return {
        "name": name.strip()[:200],
        "brand": (brand or "").strip()[:200] or None,
        "serving_size": 100.0,
        "serving_unit": "g",
        "calories": _num(nutrients.get("calories")),
        "protein": _num(nutrients.get("protein")),
        "carbs": _num(nutrients.get("carbs")),
        "fat": _num(nutrients.get("fat")),
        "fiber": _num(nutrients.get("fiber")),
        "source": source,
        "barcode": barcode,
    }


class FoodProvider(Protocol):
    """A remote food database. Implementations must never raise for remote failures."""

    source: str

    async def search(self, query: str, limit: int = 10) -> list[dict]: ...

    async def barcode(self, code: str) -> dict | None: ...


class _HttpMixin:
    """Shared GET helper; an httpx.AsyncClient may be injected (tests)."""

    _client: httpx.AsyncClient | None = None

    async def _get_json(self, url: str, params: dict[str, Any]) -> dict | None:
        try:
            if self._client is not None:
                resp = await self._client.get(url, params=params)
            else:
                async with httpx.AsyncClient(timeout=TIMEOUT, headers=HEADERS) as client:
                    resp = await client.get(url, params=params)
            if resp.status_code != 200:
                return None
            data = resp.json()
            return data if isinstance(data, dict) else None
        except (httpx.HTTPError, ValueError):
            return None


class OpenFoodFactsClient(_HttpMixin):
    source = "openfoodfacts"

    def __init__(self, client: httpx.AsyncClient | None = None):
        self._client = client

    @staticmethod
    def _parse_product(p: dict) -> dict | None:
        name = (p.get("product_name") or "").strip()
        if not name:
            return None
        n = p.get("nutriments") or {}
        brands = (p.get("brands") or "").split(",")
        code = p.get("code") or p.get("_id")
        return _normalized(
            name,
            brands[0] if brands else None,
            {
                "calories": n.get("energy-kcal_100g"),
                "protein": n.get("proteins_100g"),
                "carbs": n.get("carbohydrates_100g"),
                "fat": n.get("fat_100g"),
                "fiber": n.get("fiber_100g"),
            },
            "openfoodfacts",
            str(code) if code else None,
        )

    async def search(self, query: str, limit: int = 10) -> list[dict]:
        query = query.strip()
        if not query:
            return []
        data = await self._get_json(OFF_SEARCH_URL, {
            "search_terms": query,
            "json": 1,
            "page_size": min(limit, 20),
            "fields": "code,product_name,brands,nutriments",
        })
        products = (data or {}).get("products") or []
        out = []
        for p in products:
            if isinstance(p, dict):
                row = self._parse_product(p)
                if row is not None:
                    out.append(row)
        return out

    async def barcode(self, code: str) -> dict | None:
        data = await self._get_json(OFF_PRODUCT_URL.format(code=code), {
            "fields": "code,product_name,brands,nutriments",
        })
        if not data or data.get("status") != 1:
            return None
        product = data.get("product")
        return self._parse_product(product) if isinstance(product, dict) else None


class USDAV2Client(_HttpMixin):
    source = "usda"

    def __init__(self, api_key: str, client: httpx.AsyncClient | None = None):
        self._api_key = api_key
        self._client = client

    @staticmethod
    def _parse_food(f: dict) -> dict | None:
        name = (f.get("description") or "").strip()
        if not name:
            return None
        nutrients: dict[str, float] = {}
        for n in f.get("foodNutrients") or []:
            if not isinstance(n, dict):
                continue
            field = USDA_NUTRIENT_IDS.get(n.get("nutrientId"))
            if field:
                nutrients[field] = _num(n.get("value"))
        if not nutrients:
            return None  # no usable data — don't cache an empty shell
        return _normalized(
            name,
            f.get("brandOwner") or f.get("brandName"),
            nutrients,
            "usda",
            (f.get("gtinUpc") or "").strip() or None,
        )

    async def search(self, query: str, limit: int = 10) -> list[dict]:
        query = query.strip()
        if not self._api_key or not query:
            return []
        data = await self._get_json(USDA_SEARCH_URL, {
            "api_key": self._api_key,
            "query": query,
            "pageSize": min(limit, 20),
        })
        foods = (data or {}).get("foods") or []
        out = []
        for f in foods:
            if isinstance(f, dict):
                row = self._parse_food(f)
                if row is not None:
                    out.append(row)
        return out

    async def barcode(self, code: str) -> dict | None:
        # FDC has no barcode endpoint; a UPC/GTIN search term matches gtinUpc.
        if not self._api_key:
            return None
        digits = code.strip()
        if not digits.isdigit():
            return None
        data = await self._get_json(USDA_SEARCH_URL, {
            "api_key": self._api_key,
            "query": digits,
            "pageSize": 5,
        })
        for f in (data or {}).get("foods") or []:
            if isinstance(f, dict) and (f.get("gtinUpc") or "").lstrip("0") == digits.lstrip("0"):
                return self._parse_food(f)
        return None


def default_providers(usda_api_key: str = "") -> list[FoodProvider]:
    """Providers active for this deployment. USDA is skipped without an API key."""
    providers: list[FoodProvider] = [OpenFoodFactsClient()]
    if usda_api_key:
        providers.append(USDAV2Client(api_key=usda_api_key))
    return providers


async def search_remote(query: str, limit: int = 20, providers: list[FoodProvider] | None = None) -> list[dict]:
    """Query all active providers concurrently; failures degrade to no results."""
    if providers is None:
        from ..config import get_settings
        providers = default_providers(get_settings().usda_api_key)
    per_provider = max(1, min(limit, 20) // max(len(providers), 1)) if providers else 0
    results = await asyncio.gather(
        *(p.search(query, per_provider) for p in providers), return_exceptions=True
    )
    out: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for res in results:
        if isinstance(res, BaseException):
            continue
        for row in res:
            key = (row["name"].lower(), (row.get("brand") or "").lower())
            if key not in seen:
                seen.add(key)
                out.append(row)
            if len(out) >= limit:
                return out
    return out


async def barcode_remote(code: str, providers: list[FoodProvider] | None = None) -> dict | None:
    """Look up a barcode across providers in order; first hit wins."""
    if providers is None:
        from ..config import get_settings
        providers = default_providers(get_settings().usda_api_key)
    for provider in providers:
        try:
            hit = await provider.barcode(code)
        except Exception:
            hit = None
        if hit is not None:
            return hit
    return None
