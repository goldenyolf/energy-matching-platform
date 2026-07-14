FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install dependencies first (better layer caching).
COPY pyproject.toml README.md ./
COPY app ./app
RUN pip install --upgrade pip && pip install ".[dashboard]"

# Copy the rest of the project.
COPY alembic.ini ./
COPY alembic ./alembic
COPY dashboard ./dashboard
COPY data ./data
COPY scripts ./scripts

EXPOSE 8000 8501

# Default: run the API. Compose overrides the command per service.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
