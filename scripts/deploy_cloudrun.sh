#!/usr/bin/env bash
#
# Deploy the Energy Matching Platform to Google Cloud Run.
#
# Builds ONE image from the Dockerfile, runs DB migrations as a Cloud Run Job,
# then deploys the API service (which also serves the SPA at /app) and seeds demo data.
# Database is external PostgreSQL (Neon recommended) via DATABASE_URL.
#
# Prerequisites:
#   - gcloud CLI installed and authenticated: gcloud auth login
#   - A GCP project with billing enabled
#
# Usage:
#   export PROJECT_ID="your-gcp-project"
#   export DATABASE_URL="postgresql+psycopg://user:pass@host/db?sslmode=require"
#   ./scripts/deploy_cloudrun.sh
#
# Optional overrides:
#   REGION (default asia-east1 = Taiwan), REPO, IMAGE_TAG, SEED (default true)

set -euo pipefail

: "${PROJECT_ID:?Set PROJECT_ID}"
: "${DATABASE_URL:?Set DATABASE_URL (postgresql+psycopg://...)}"
REGION="${REGION:-asia-east1}"
REPO="${REPO:-energy-matching}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
SEED="${SEED:-true}"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/app:${IMAGE_TAG}"

echo "==> Project=${PROJECT_ID} Region=${REGION} Image=${IMAGE}"
gcloud config set project "${PROJECT_ID}" >/dev/null

echo "==> Enabling required APIs (one-time)"
gcloud services enable \
  run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com

echo "==> Ensuring Artifact Registry repo exists"
gcloud artifacts repositories create "${REPO}" \
  --repository-format=docker --location="${REGION}" \
  --description="Energy Matching Platform" 2>/dev/null || true

echo "==> Building & pushing image with Cloud Build"
gcloud builds submit --tag "${IMAGE}"

echo "==> Running database migrations (Cloud Run Job)"
gcloud run jobs deploy emp-migrate \
  --image "${IMAGE}" --region "${REGION}" \
  --set-env-vars "DATABASE_URL=${DATABASE_URL}" \
  --command sh --args '-c,alembic upgrade head'
gcloud run jobs execute emp-migrate --region "${REGION}" --wait

echo "==> Deploying API service (emp-api)"
gcloud run deploy emp-api \
  --image "${IMAGE}" --region "${REGION}" --allow-unauthenticated \
  --set-env-vars "DATABASE_URL=${DATABASE_URL},ENVIRONMENT=production" \
  --command sh \
  --args '-c,uvicorn app.main:app --host 0.0.0.0 --port $PORT'

API_URL="$(gcloud run services describe emp-api --region "${REGION}" \
  --format 'value(status.url)')"
echo "==> API deployed at ${API_URL} (SPA at ${API_URL}/app/)"

if [ "${SEED}" = "true" ]; then
  echo "==> Seeding demo data (Cloud Run Job)"
  gcloud run jobs deploy emp-seed \
    --image "${IMAGE}" --region "${REGION}" \
    --set-env-vars "DATABASE_URL=${DATABASE_URL}" \
    --command sh --args '-c,python -m scripts.seed --reset'
  gcloud run jobs execute emp-seed --region "${REGION}" --wait
fi

echo ""
echo "======================================================================"
echo " Done."
echo "  Web UI (SPA)  : ${API_URL}/app/"
echo "  API / Swagger : ${API_URL}/docs"
echo "======================================================================"
