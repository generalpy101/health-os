"""Track B: reviews (offline narrative), background job lifecycle, chat streaming, push."""

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("AI_PROVIDER", "mock")
os.environ.setdefault("WORKER_ENABLED", "false")  # job lifecycle is driven explicitly here

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app import worker
from app.config import get_settings
from app.db import SessionLocal
from app.main import app
from app.models import BackgroundJob


@pytest.fixture
async def client():
    get_settings().worker_enabled = False  # settings may already be cached from another module
    # distinct client host -> own rate-limit bucket (signup is limited to 5/min)
    transport = ASGITransport(app=app, client=("10.9.8.7", 9999))
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        async with app.router.lifespan_context(app):
            yield c


async def _auth(client: AsyncClient, email: str = "trackb@example.com") -> None:
    # the in-memory DB is wiped when each lifespan ends (engine.dispose), so every
    # test signs up fresh inside its own lifespan
    r = await client.post("/api/v1/auth/signup", json={"email": email, "password": "password123", "name": "T"})
    assert r.status_code == 201, r.text


# ---------- reviews ----------

@pytest.mark.asyncio
async def test_weekly_review_offline_narrative(client):
    api = "/api/v1"
    await _auth(client)
    await client.post(f"{api}/workout-sessions", json={
        "title": "Push", "exercises": [{"name": "Bench", "sets": [{"weight": 60, "reps": 10}] * 3}]})
    await client.post(f"{api}/food-logs", json={
        "meal_type": "lunch", "items": [{"name": "Rice", "quantity": 200, "unit": "g",
                                         "calories": 260, "protein": 5, "carbs": 56, "fat": 1}]})

    r = await client.get(f"{api}/reviews/weekly")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["data"]["days"] == 7
    assert body["narrative"]  # deterministic mock template — works offline
    assert "trained 1 time" in body["narrative"]
    assert len(body["narrative"].split()) <= 120
    assert body["start"] and body["end"] and body["generated_at"]

    # second read is served from cache (same generated_at)
    r2 = await client.get(f"{api}/reviews/weekly")
    assert r2.json()["generated_at"] == body["generated_at"]

    # regenerate returns the cached version and enqueues a background refresh
    r3 = await client.post(f"{api}/reviews/weekly/regenerate")
    assert r3.status_code == 200, r3.text
    assert r3.json()["generated_at"] == body["generated_at"]
    async with SessionLocal() as db:
        jobs = (await db.execute(
            select(BackgroundJob).where(BackgroundJob.kind == "generate_review")
        )).scalars().all()
    assert len(jobs) == 1 and jobs[0].status == "pending" and jobs[0].payload["kind"] == "weekly"

    # the queued job, once run, refreshes the cached row
    await worker.run_due_jobs()
    r4 = await client.get(f"{api}/reviews/weekly")
    assert r4.json()["generated_at"] != body["generated_at"]
    assert "trained 1 time" in r4.json()["narrative"]

    # a weekly review older than 20h lazily enqueues a refresh, serves the cache meanwhile
    from app.models import Review
    stale_at = datetime.now(timezone.utc) - timedelta(hours=21)
    async with SessionLocal() as db:
        review = (await db.execute(select(Review))).scalars().one()
        review.generated_at = stale_at
        await db.commit()
    r5 = await client.get(f"{api}/reviews/weekly")
    assert r5.json()["generated_at"].startswith(stale_at.isoformat()[:19])  # cached copy
    async with SessionLocal() as db:
        pending = (await db.execute(
            select(BackgroundJob).where(BackgroundJob.kind == "generate_review",
                                        BackgroundJob.status == "pending")
        )).scalars().all()
    assert len(pending) == 1


@pytest.mark.asyncio
async def test_monthly_review(client):
    api = "/api/v1"
    await _auth(client)
    r = await client.get(f"{api}/reviews/monthly")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["start"].endswith("01")  # month-to-date period
    assert body["narrative"] is not None
    r2 = await client.post(f"{api}/reviews/monthly/regenerate")
    assert r2.status_code == 200
    assert r2.json()["narrative"] == body["narrative"]  # cached copy returned meanwhile


# ---------- background jobs ----------

@pytest.mark.asyncio
async def test_job_lifecycle_pending_to_done(client):
    seen = []

    @worker.handler("test_noop")
    async def _noop(db, job):
        seen.append(job.payload.get("x"))

    async with SessionLocal() as db:
        job = await worker.enqueue(db, "test_noop", {"x": 1})
        await db.commit()
        assert job.status == "pending"

        await worker.run_due_jobs()
        await db.refresh(job)
        assert seen == [1]
        assert job.status == "done"
        assert job.attempts == 1


@pytest.mark.asyncio
async def test_job_backoff_then_failed(client):
    calls = []

    @worker.handler("test_boom")
    async def _boom(db, job):
        calls.append(job.attempts)
        raise RuntimeError("boom")

    async with SessionLocal() as db:
        job = await worker.enqueue(db, "test_boom", {})
        await db.commit()

        now = datetime.now(timezone.utc)
        await worker.run_due_jobs(now)  # attempt 1 fails -> pending with backoff
        await db.refresh(job)
        assert job.status == "pending" and job.attempts == 1
        assert job.run_at.replace(tzinfo=timezone.utc) > now  # retried later, not immediately
        assert "boom" in job.last_error

        later = now + timedelta(seconds=30)
        await worker.run_due_jobs(later)  # attempt 2 fails
        await db.refresh(job)
        assert job.status == "pending" and job.attempts == 2

        await worker.run_due_jobs(later + timedelta(seconds=30))  # attempt 3 -> failed
        await db.refresh(job)
        assert job.status == "failed" and job.attempts == 3
        assert calls == [1, 2, 3]


# ---------- streaming chat ----------

def _parse_sse(body: str) -> list[tuple[str, dict]]:
    out = []
    for block in body.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        event, data = "", ""
        for line in block.splitlines():
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                data += line[5:].strip()
        out.append((event, json.loads(data)))
    return out


@pytest.mark.asyncio
async def test_chat_stream_emits_sse_events(client):
    api = "/api/v1"
    await _auth(client)

    body = ""
    async with client.stream("POST", f"{api}/ai/chat/stream", json={"message": "weighed 80.5"}) as r:
        assert r.status_code == 200, await r.aread()
        assert r.headers["content-type"].startswith("text/event-stream")
        async for chunk in r.aiter_text():
            body += chunk

    events = _parse_sse(body)
    kinds = [e for e, _ in events]
    assert "delta" in kinds and "actions" in kinds and "done" in kinds

    actions = next(d for e, d in events if e == "actions")["actions"]
    assert any(a["tool"] == "record_measurement" and a["status"] == "executed" for a in actions)

    done = next(d for e, d in events if e == "done")
    assert done["conversation_id"] and done["reply"]
    deltas = "".join(d["text"] for e, d in events if e == "delta")
    assert deltas == done["reply"]  # mock provider: one delta carrying the full reply

    # same conversation continues over the stream
    r = await client.get(f"{api}/ai/conversations/{done['conversation_id']}/messages")
    assert [m["role"] for m in r.json()] == ["user", "assistant"]


# ---------- push ----------

@pytest.mark.asyncio
async def test_push_subscribe_and_test(client, tmp_path, monkeypatch):
    from app.services import push as push_service

    monkeypatch.setattr(push_service, "VAPID_PATH", tmp_path / "vapid.json")
    api = "/api/v1"
    await _auth(client)

    r = await client.get(f"{api}/push/vapid-key")
    assert r.status_code == 200 and len(r.json()["publicKey"]) > 20
    assert (tmp_path / "vapid.json").exists()  # keypair generated once, on demand

    sub = {"endpoint": "http://127.0.0.1:9/unreachable", "keys": {"p256dh": "x", "auth": "y"}}
    r = await client.post(f"{api}/push/subscribe", json=sub)
    assert r.status_code == 201, r.text

    # unreachable endpoint: send fails as "error" (not 404/410), sub is kept
    r = await client.post(f"{api}/push/test")
    assert r.status_code == 200 and r.json() == {"sent": 0}
    async with SessionLocal() as db:
        from app.models import PushSubscription
        subs = (await db.execute(select(PushSubscription))).scalars().all()
        assert len(subs) == 1

    r = await client.request("DELETE", f"{api}/push/subscribe", json={"endpoint": sub["endpoint"]})
    assert r.status_code == 204
    async with SessionLocal() as db:
        from app.models import PushSubscription
        assert (await db.execute(select(PushSubscription))).scalars().all() == []
