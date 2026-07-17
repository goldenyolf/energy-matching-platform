#!/bin/sh
# Render / container entrypoint for the FastAPI service.
# Runs migrations (idempotent) then serves the API + static SPA on $PORT.
set -e
alembic upgrade head
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
