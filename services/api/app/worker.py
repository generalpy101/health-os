"""In-process background worker. No Redis: jobs live in the `background_jobs`
table and an asyncio task (started in the FastAPI lifespan) polls for due work.

Semantics:
- poll every POLL_SECONDS for pending jobs with run_at <= now
- a handler runs with its own session; success -> done, exception -> retry with
  exponential backoff (5s, 10s, 20s), giving up after MAX_ATTEMPTS -> failed
- jobs left in `running` by a crash are re-queued on startup
- the loop self-heals the recurring `check_reminders` job (every 15 min); each
  run also enqueues its own successor, the loop only backstops a broken chain
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextlib import suppress
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import get_settings
from .db import SessionLocal
from .models import BackgroundJob, User

log = logging.getLogger(__name__)

POLL_SECONDS = 10
BATCH_LIMIT = 10
MAX_ATTEMPTS = 3
BACKOFF_BASE_SECONDS = 5
REMINDERS_EVERY = timedelta(minutes=15)

Handler = Callable[[AsyncSession, BackgroundJob], Awaitable[None]]
HANDLERS: dict[str, Handler] = {}


def handler(kind: str) -> Callable[[Handler], Handler]:
    def deco(fn: Handler) -> Handler:
        HANDLERS[kind] = fn
        return fn
    return deco


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def enqueue(db: AsyncSession, kind: str, payload: dict | None = None,
                  user_id=None, run_at: datetime | None = None) -> BackgroundJob:
    job = BackgroundJob(kind=kind, payload=payload or {}, user_id=user_id,
                        run_at=run_at or datetime.now(timezone.utc))
    db.add(job)
    await db.flush()
    return job


# ---------------------------------------------------------------------------
# job handlers
# ---------------------------------------------------------------------------

@handler("generate_review")
async def _generate_review(db: AsyncSession, job: BackgroundJob) -> None:
    from .services import reviews as reviews_service

    user = await db.get(User, job.user_id) if job.user_id else None
    if user is None:
        return  # nothing to do; runner marks the job done, no point retrying
    await reviews_service.run_generate_review(db, user, job.payload.get("kind", "weekly"))


@handler("extract_observations")
async def _extract_observations(db: AsyncSession, job: BackgroundJob) -> None:
    """Daily: mine behavior patterns into memory records for every user, then
    self-enqueue tomorrow's run (same chain pattern as check_reminders)."""
    from .services import observations as observations_service

    user_ids = (await db.execute(select(User.id))).scalars().all()
    for uid in user_ids:
        user = await db.get(User, uid)
        if user is not None:
            await observations_service.extract_observations(db, user)
    await enqueue(db, "extract_observations", {}, run_at=datetime.now(timezone.utc) + timedelta(hours=24))
    await db.commit()


@handler("onboarding_parse")
async def _onboarding_parse(db: AsyncSession, job: BackgroundJob) -> None:
    """Long-running onboarding extraction (CLI/hosted LLMs can take 30-60s).

    The proposal lands in job.payload["result"]; the client polls GET /ai/jobs/{id}.
    """
    from .ai import service as ai_service

    user = await db.get(User, job.user_id) if job.user_id else None
    if user is None:
        return
    result = await ai_service.parse_onboarding(db, user, job.payload.get("text", ""))
    job.payload = {**job.payload, "result": result}


@handler("check_reminders")
async def _check_reminders(db: AsyncSession, job: BackgroundJob) -> None:
    """Push a heads-up for schedule events starting within the user's next 30 min.

    Sent occurrences are tracked in the job payload ({"sent": {occurrence_key: date}})
    which is carried forward to the successor job — one push per occurrence.
    """
    from zoneinfo import ZoneInfo

    from .models import PushSubscription
    from .services import push as push_service
    from .services import schedule as schedule_service
    from .utils.time import user_now

    sent: dict[str, str] = dict(job.payload.get("sent") or {})
    user_ids = (await db.execute(select(PushSubscription.user_id).distinct())).scalars().all()
    for user_id in user_ids:
        user = await db.get(User, user_id)
        if user is None:
            continue
        now = user_now(user.timezone)
        events = await schedule_service.get_schedule(db, user, now.date(), now.date())
        for e in events:
            start = e["start_at"]
            mins = (start - now).total_seconds() / 60
            if not (0 <= mins <= 30):
                continue
            key = f"{e['id']}:{start.isoformat()}"
            if key in sent:
                continue
            local_start = start.astimezone(ZoneInfo(user.timezone))
            count = await push_service.send_to_user(
                db, user, "HealthOS", f"{e['title']} — starts at {local_start:%H:%M}", url="/schedule")
            if count:
                sent[key] = now.date().isoformat()

    # hand the sent-set to the next run; keep it bounded (recent days only)
    cutoff = (datetime.now(timezone.utc).date() - timedelta(days=2)).isoformat()
    payload = {"sent": {k: v for k, v in sent.items() if v >= cutoff}}
    await enqueue(db, "check_reminders", payload, run_at=datetime.now(timezone.utc) + REMINDERS_EVERY)
    await db.commit()


async def _ensure_reminder_job(db: AsyncSession) -> None:
    """Backstop: guarantee pending/running chains exist for the recurring jobs."""
    for kind, delay in (("check_reminders", None), ("extract_observations", timedelta(hours=24))):
        existing = (await db.execute(
            select(BackgroundJob.id).where(BackgroundJob.kind == kind,
                                           BackgroundJob.status.in_(("pending", "running"))).limit(1)
        )).first()
        if existing is None:
            await enqueue(db, kind, {"sent": {}} if kind == "check_reminders" else {},
                          run_at=datetime.now(timezone.utc) + delay if delay else None)
    await db.commit()


# ---------------------------------------------------------------------------
# runner
# ---------------------------------------------------------------------------

async def run_due_jobs(now: datetime | None = None) -> int:
    """Run every due pending job once. Returns how many jobs were attempted."""
    now = now or datetime.now(timezone.utc)
    ran = 0
    async with SessionLocal() as db:
        jobs = (await db.execute(
            select(BackgroundJob).where(BackgroundJob.status == "pending")
            .order_by(BackgroundJob.run_at).limit(BATCH_LIMIT)
        )).scalars().all()
        due = [j for j in jobs if _aware(j.run_at) <= now]
        for job in due:
            job.status = "running"
            job.attempts += 1
            await db.commit()
            ran += 1
            fn = HANDLERS.get(job.kind)
            try:
                if fn is None:
                    raise ValueError(f"no handler registered for job kind {job.kind!r}")
                await fn(db, job)
                job.status = "done"
                job.last_error = None
            except Exception as exc:
                await db.rollback()  # handler may have partial uncommitted state
                log.warning("job %s (%s) failed on attempt %s: %s", job.id, job.kind, job.attempts, exc)
                job.last_error = f"{type(exc).__name__}: {exc}"[:2000]
                if job.attempts >= MAX_ATTEMPTS:
                    job.status = "failed"
                else:
                    job.status = "pending"
                    job.run_at = now + timedelta(seconds=BACKOFF_BASE_SECONDS * 2 ** (job.attempts - 1))
            await db.commit()
    return ran


async def recover_stale_jobs() -> None:
    """Re-queue jobs orphaned in `running` by a previous process."""
    async with SessionLocal() as db:
        stale = (await db.execute(
            select(BackgroundJob).where(BackgroundJob.status == "running")
        )).scalars().all()
        for job in stale:
            job.status = "pending"
            job.attempts = 0
        if stale:
            await db.commit()


async def _loop() -> None:
    # first tick only after a full interval: lets the app finish booting, and
    # keeps short-lived processes (tests) from touching the DB at all
    await asyncio.sleep(POLL_SECONDS)
    await recover_stale_jobs()
    while True:
        try:
            async with SessionLocal() as db:
                await _ensure_reminder_job(db)
            await run_due_jobs()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("background worker tick failed")
        await asyncio.sleep(POLL_SECONDS)


def start_worker() -> asyncio.Task | None:
    if not get_settings().worker_enabled:
        return None
    return asyncio.create_task(_loop())


async def stop_worker(task: asyncio.Task | None) -> None:
    if task is None:
        return
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
