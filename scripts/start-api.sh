#!/bin/sh
# Render / container entrypoint for the FastAPI service.
# Runs migrations (idempotent) then serves the API + static SPA on $PORT.
#
# Demo seeding without a shell (set the env var in Render → Environment):
#   SEED_ON_START=1  -> seed the bundled sample demo ONLY IF the DB is empty.
#                       Non-destructive and safe to leave on: it does nothing
#                       once data exists, so a forgotten flag can't wipe data.
#   SEED_RESET=1     -> DROP every table and reseed from scratch. Destructive;
#                       set it for a one-off reset, then REMOVE it immediately.
set -e
alembic upgrade head
if [ "$SEED_RESET" = "1" ] || [ "$SEED_RESET" = "true" ]; then
  echo ">>> SEED_RESET set — DROPPING all tables and reseeding sample demo…"
  python -m scripts.seed --reset --source sample || \
    echo ">>> WARNING: seed failed; continuing to serve existing data"
elif [ "$SEED_ON_START" = "1" ] || [ "$SEED_ON_START" = "true" ]; then
  echo ">>> SEED_ON_START set — seeding sample demo only if the DB is empty…"
  python -m scripts.seed --if-empty --source sample || \
    echo ">>> WARNING: seed failed; continuing to serve existing data"
fi
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
