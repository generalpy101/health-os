#!/usr/bin/env bash
# Local mode: Postgres in Docker, API + web on the host.
# Use this mode if you want local AI CLIs (Claude Code, Codex, opencode)
# or a local Ollama/LM Studio server as the AI provider — the API process
# can only reach them when it runs on your machine, not inside a container.
set -euo pipefail
cd "$(dirname "$0")/.."

docker compose up -d db
until docker exec healthos-db-1 pg_isready -U healthos >/dev/null 2>&1; do sleep 1; done

export DATABASE_URL="postgresql+asyncpg://healthos:healthos@localhost:5432/healthos"
export DOCKERIZED=""          # host mode: providers probe localhost
export STORAGE_DIR="$(pwd)/services/api/data/photos"

if [ ! -d .venv ]; then
  python3 -m venv .venv
  ./.venv/bin/pip install -q -r services/api/requirements-dev.txt
fi

./.venv/bin/python -m uvicorn app.main:app --port 8000 --reload --app-dir services/api &
API_PID=$!

(cd apps/web && pnpm install --frozen-lockfile && API_INTERNAL_URL=http://localhost:8000 pnpm dev) &
WEB_PID=$!

trap 'kill $API_PID $WEB_PID 2>/dev/null || true' EXIT
echo ""
echo "  HealthOS local mode"
echo "  web: http://localhost:3000   api: http://localhost:8000/docs"
echo "  DB: docker (healthos-db-1). Ctrl+C stops web+api (db keeps running)."
wait
