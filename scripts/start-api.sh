#!/bin/sh
# Render / container entrypoint for the FastAPI service.
# Runs migrations (idempotent) then serves the API + static SPA on $PORT.
#
# One-time demo seeding without a shell: set the env var SEED_ON_START=1 (Render
# → Environment), redeploy, then REMOVE the var. On start it reloads the bundled
# sample demo (with time slots + meters). It resets the DB each start while set,
# so unset it once the demo data is in.
set -e
alembic upgrade head
if [ "$SEED_ON_START" = "1" ] || [ "$SEED_ON_START" = "true" ]; then
  echo ">>> SEED_ON_START set — reloading sample demo data (reset)…"
  python -m scripts.seed --reset --source sample || \
    echo ">>> WARNING: seed failed; continuing to serve existing data"
fi
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
