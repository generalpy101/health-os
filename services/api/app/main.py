from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .db import SessionLocal, engine, init_db
from .routers import ai, analytics, auth, fitness, goals, health, nutrition, recipes, schedule, users
from .seed import seed


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    settings = get_settings()
    if settings.seed_on_startup:
        async with SessionLocal() as db:
            await seed(db)
    yield
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


@app.get("/healthz")
async def healthz():
    return {"ok": True}
