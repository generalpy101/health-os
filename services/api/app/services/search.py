"""Search (Track C): fast ILIKE lookup + optional semantic search.

Semantic search is honest and portable: embeddings come from the user's own
OpenAI-compatible provider (Settings -> AI), are cached in the `embeddings`
table as plain JSON float lists, and cosine similarity runs in Python over the
(small) per-user corpus. No pgvector dependency, works on SQLite.
"""

import hashlib
import math
from typing import Any

import httpx
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..ai.registry import PRESET_BY_ID, _is_local_url, get_ai_pref
from ..models import AIConversation, Embedding, Exercise, Food, Recipe, User, UserMemory, UserPreference

SEARCH_NOT_CONFIGURED = "semantic search needs an embeddings-capable provider (Settings → AI)"
SCORE_THRESHOLD = 0.2
MAX_CORPUS = 200  # per entity type; personal corpora are small


async def search_all(db: AsyncSession, user: User, q: str, limit: int = 8) -> dict:
    like = f"%{q.strip()}%"
    foods = (await db.execute(
        select(Food).where(or_(Food.user_id == user.id, Food.user_id.is_(None)),
                           Food.name.ilike(like))
        .order_by(Food.name).limit(limit)
    )).scalars().all()
    recipes = (await db.execute(
        select(Recipe).where(Recipe.user_id == user.id, Recipe.name.ilike(like))
        .order_by(Recipe.name).limit(limit)
    )).scalars().all()
    exercises = (await db.execute(
        select(Exercise).where(Exercise.name.ilike(like)).order_by(Exercise.name).limit(limit)
    )).scalars().all()
    convs = (await db.execute(
        select(AIConversation).where(AIConversation.user_id == user.id,
                                     AIConversation.title.ilike(like))
        .order_by(AIConversation.updated_at.desc()).limit(limit)
    )).scalars().all()
    return {
        "foods": [{"id": str(f.id), "name": f.name, "calories": f.calories} for f in foods],
        "recipes": [{"id": str(r.id), "name": r.name} for r in recipes],
        "exercises": [{"id": str(e.id), "name": e.name} for e in exercises],
        "conversations": [{"id": str(c.id), "title": c.title} for c in convs],
    }


# ---------- semantic ----------

def _embedding_config(ai: dict) -> tuple[str, str, str] | None:
    """(base_url, model, api_key) if the user's AI provider can embed, else None."""
    preset = PRESET_BY_ID.get(ai.get("provider") or "")
    if preset is None or preset.kind != "openai_compatible":
        return None
    base_url = (ai.get("base_url") or preset.default_base_url or "").rstrip("/")
    if not base_url:
        return None
    if ai.get("mode", "hybrid") == "local-only" and not _is_local_url(base_url):
        return None  # privacy mode forbids this endpoint
    # ollama (":11434") chat models don't embed -> default to nomic-embed-text;
    # an explicit embed_model pref always wins.
    model = ai.get("embed_model") or (
        "nomic-embed-text" if ":11434" in base_url else (ai.get("model") or "")
    )
    if not model:
        return None
    return base_url, model, ai.get("api_key") or ""


async def _embed(base_url: str, model: str, api_key: str, texts: list[str]) -> list[list[float]]:
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(f"{base_url}/embeddings", headers=headers,
                                 json={"model": model, "input": texts})
        resp.raise_for_status()
        data = resp.json()
    return [item["embedding"] for item in data["data"]]


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _text_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


async def _corpus(db: AsyncSession, user: User) -> list[dict[str, Any]]:
    """(entity_type, entity_id, text) for everything semantic search covers."""
    items: list[dict[str, Any]] = []
    recipes = (await db.execute(
        select(Recipe).where(Recipe.user_id == user.id).limit(MAX_CORPUS)
    )).scalars().all()
    for r in recipes:
        text = " ".join([r.name, r.description or "", " ".join(r.tags or []), r.cuisine or ""]).strip()
        items.append({"entity_type": "recipe", "entity_id": str(r.id), "text": text})
    foods = (await db.execute(
        select(Food).where(or_(Food.user_id == user.id, Food.user_id.is_(None))).limit(MAX_CORPUS)
    )).scalars().all()
    for f in foods:
        items.append({"entity_type": "food", "entity_id": str(f.id),
                      "text": " ".join([f.name, f.brand or ""]).strip()})
    memories = (await db.execute(
        select(UserMemory).where(UserMemory.user_id == user.id,
                                 UserMemory.status.in_(["active", "confirmed"])).limit(MAX_CORPUS)
    )).scalars().all()
    for m in memories:
        items.append({"entity_type": "memory", "entity_id": str(m.id),
                      "text": f"{m.key.replace('_', ' ')}: {m.value.get('value', '')}"})
    return items


async def semantic_search(db: AsyncSession, user: User, q: str, limit: int = 10) -> dict:
    pref = (await db.execute(
        select(UserPreference).where(UserPreference.user_id == user.id)
    )).scalar_one_or_none()
    config = _embedding_config(get_ai_pref(pref))
    if config is None:
        return {"results": [], "message": SEARCH_NOT_CONFIGURED}
    base_url, model, api_key = config

    corpus = await _corpus(db, user)
    if not corpus:
        return {"results": []}

    # reuse cached embeddings whose text + model are unchanged
    cached = (await db.execute(
        select(Embedding).where(Embedding.user_id == user.id, Embedding.model == model)
    )).scalars().all()
    cache = {(e.entity_type, e.entity_id): e for e in cached}
    to_embed = [it for it in corpus
                if cache.get((it["entity_type"], it["entity_id"])) is None
                or cache[(it["entity_type"], it["entity_id"])].text_hash != _text_hash(it["text"])]

    try:
        query_vec = (await _embed(base_url, model, api_key, [q]))[0]
        for chunk_start in range(0, len(to_embed), 32):
            chunk = to_embed[chunk_start:chunk_start + 32]
            vectors = await _embed(base_url, model, api_key, [it["text"] for it in chunk])
            for it, vec in zip(chunk, vectors):
                row = cache.get((it["entity_type"], it["entity_id"]))
                if row is None:
                    row = Embedding(user_id=user.id, entity_type=it["entity_type"],
                                    entity_id=it["entity_id"])
                    db.add(row)
                row.model = model
                row.text_hash = _text_hash(it["text"])
                row.vector = vec
                cache[(it["entity_type"], it["entity_id"])] = row
        if to_embed:
            await db.commit()
    except Exception as exc:
        await db.rollback()
        return {"results": [], "message": f"embedding provider failed: {type(exc).__name__}"}

    scored = []
    for it in corpus:
        row = cache.get((it["entity_type"], it["entity_id"]))
        if row is None or not row.vector:
            continue
        score = _cosine(query_vec, row.vector)
        if score >= SCORE_THRESHOLD:
            scored.append({"entity_type": it["entity_type"], "entity_id": it["entity_id"],
                           "snippet": it["text"][:160], "score": round(score, 4)})
    scored.sort(key=lambda r: r["score"], reverse=True)
    return {"results": scored[:limit]}
