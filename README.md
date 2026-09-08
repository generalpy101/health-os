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

## AI providers (per-user, switchable in-app)

Pick a provider anytime: **Settings → AI**, the chip in the **Assistant header**, the **sidebar**, or during **onboarding**.

| Provider | Runs where | Notes |
| --- | --- | --- |
| Built-in offline (mock) | server | Deterministic; handles common logging phrasing; zero setup, zero keys |
| OpenAI | cloud | Your key, stored server-side, never sent to the browser |
| Ollama / LM Studio | your machine | Auto-detected; OpenAI-compatible endpoints |
| Custom endpoint | anywhere | Any `/v1/chat/completions` (vLLM, LiteLLM, Groq, Together…) |
| Claude Code / Codex / opencode | your machine | Uses your existing CLI logins, driven non-interactively with a strict JSON tool contract |

**Using local CLIs (claude/codex/opencode) or a local model server:** the API must run on your
machine (containers can't see host CLIs). Use local mode — DB stays in Docker:

```bash
./scripts/dev-local.sh
```

Then Settings → AI → pick e.g. "Claude Code (CLI)" → Test connection.

## Migrations

Alembic runs automatically at API startup (`alembic upgrade head`; a pre-existing database is
stamped first). New revision after a model change:

```bash
cd services/api
DATABASE_URL=postgresql+asyncpg://healthos:healthos@localhost:5432/healthos ../../.venv/bin/alembic revision --autogenerate -m "..."
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

All under `/api/v1`: `auth/*`, `users/me*` (+ `users/me/export`, `DELETE /users/me`), `goals`,
`targets`, `foods/search`, `food-logs`, `nutrition/daily`, `recipes`, `meal-plans`, `grocery-list`,
`exercises`, `workout-sessions`, `workout-plans`, `activities`, `sleep`, `water`, `measurements`,
`habits*`, `schedule/*`, `analytics/daily|weekly|monthly|range`, `ai/chat`, `ai/conversations`,
`ai/onboarding/*`, `ai/providers`, `ai/settings`, `ai/test`, `ai/recommendations`, `photos*`,
`notifications`. OpenAPI docs at `http://localhost:8000/docs` when the API runs.

## Not a medical device

Wellness tracking only. No diagnosis, no prescriptions — the assistant points to professionals
for medical concerns.
