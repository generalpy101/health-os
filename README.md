# HealthOS

AI-native personal health & fitness operating system — a mobile-first PWA that combines goals,
nutrition, training, sleep, hydration, habits, scheduling and progress tracking around an
assistant that operates the app through validated tools.

## Stack

| Layer | Tech |
| --- | --- |
| Web (PWA) | Next.js 15, TypeScript, Tailwind v4, TanStack Query, Recharts |
| API | FastAPI, SQLAlchemy 2 (async), Pydantic v2 |
| DB | PostgreSQL 16 (+pgvector ready), JSONB for flexible payloads |
| AI | Provider abstraction — works fully offline via `mock` provider; OpenAI-compatible (OpenAI / Ollama / vLLM) via env config |

## Quick start (Docker)

```bash
docker compose up -d --build
```

Then open **http://localhost:3000** — create an account, describe your goals in one paragraph,
review the generated plan, and start logging.

Optional environment: copy `.env.example` to `.env` and set `AUTH_SECRET`, `AI_PROVIDER`, etc.

## Local development (no Docker)

```bash
# API (SQLite fallback — zero deps beyond pip)
cd services/api
python -m venv ../../.venv && ../../.venv/bin/pip install -r requirements-dev.txt
../../.venv/bin/uvicorn app.main:app --reload --port 8000

# Web
cd apps/web
pnpm install && pnpm dev   # http://localhost:3000 (proxies /api/v1 -> localhost:8000)
```

## Tests

```bash
cd services/api && ../../.venv/bin/pytest -q
```

## Architecture

- **Structured data first** — AI output becomes typed, validated records; AI text is never the source of truth.
- **Deterministic math** — calories, macros, trends, BMI/BMR/TDEE, volume, adherence are computed in `services/api/app/utils/metrics.py`, never by the model.
- **Tool-gated AI** — the assistant can only act through the typed tool registry (`app/ai/tools.py`); every action is validated, executed via services, and audited in `ai_actions`.
- **Ownership everywhere** — every user-scoped query enforces `user_id` server-side.
- **Offline tolerance** — service worker caches reads; quick-log mutations queue in a local outbox and replay on reconnect.
- **AI failure is safe** — every screen works with `AI_PROVIDER=mock` or no provider at all.

## Repo layout

```
apps/web          Next.js PWA
services/api      FastAPI service (app/ = code, tests/ = pytest)
docker-compose.yml
```

## API surface

All under `/api/v1`: `auth/*`, `users/me*`, `goals`, `targets`, `foods/search`, `food-logs`,
`nutrition/daily`, `recipes`, `meal-plans`, `grocery-list`, `exercises`, `workout-sessions`,
`workout-plans`, `activities`, `sleep`, `water`, `measurements`, `habits*`, `schedule/*`,
`analytics/daily|weekly|monthly|range`, `ai/chat`, `ai/conversations`, `ai/onboarding/*`.
OpenAPI docs at `http://localhost:8000/docs` when the API runs.

## Not a medical device

Wellness tracking only. No diagnosis, no prescriptions — the assistant points to professionals
for medical concerns.
