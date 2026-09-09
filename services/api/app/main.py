from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .db import SessionLocal, engine
from .migrate import run_migrations
from .ratelimit import RateLimitMiddleware
from .routers import (ai, analytics, auth, fitness, goals, health, imports, notifications, nutrition,
                      photos, push, recipes, reviews, schedule, users)
from .routers import platform  # TRACK C
from .seed import seed
from .worker import start_worker, stop_worker


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    await run_migrations()
    if settings.seed_on_startup:
        async with SessionLocal() as db:
            await seed(db)
    worker = start_worker()
    try:
        yield
    finally:
        await stop_worker(worker)
    await engine.dispose()


app = FastAPI(title="HealthOS API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

API = "/api/v1"
app.include_router(auth.router, prefix=API)
app.include_router(users.router, prefix=API)
app.include_router(goals.router, prefix=API)
app.include_router(nutrition.router, prefix=API)
app.include_router(recipes.router, prefix=API)
app.include_router(fitness.router, prefix=API)
app.include_router(health.router, prefix=API)
app.include_router(schedule.router, prefix=API)
app.include_router(analytics.router, prefix=API)
app.include_router(ai.router, prefix=API)
app.include_router(photos.router, prefix=API)
app.include_router(notifications.router, prefix=API)
app.include_router(platform.router, prefix=API)  # TRACK C
# TRACK A
app.include_router(imports.router, prefix=API)
# TRACK B
app.include_router(reviews.router, prefix=API)
app.include_router(push.router, prefix=API)

app.add_middleware(RateLimitMiddleware)


@app.get("/healthz")
async def healthz():
    return {"ok": True}
