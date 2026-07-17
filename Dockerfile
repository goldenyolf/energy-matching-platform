FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install dependencies first (better layer caching).
COPY pyproject.toml README.md ./
COPY app ./app
RUN pip install --upgrade pip && pip install .

# Copy the rest of the project.
COPY alembic.ini ./
COPY alembic ./alembic
COPY web ./web
COPY data ./data
COPY scripts ./scripts

EXPOSE 8000

# Default: run the API (also serves the static SPA at /app). Render/Compose
# override this via scripts/start-api.sh (migrate + serve).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
