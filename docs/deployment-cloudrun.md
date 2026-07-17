# Deployment (Google Cloud Run + Neon Postgres)

Deploy the platform as **one Cloud Run service** (the FastAPI app, which also
serves the static SPA at `/app`) built from the `Dockerfile`, backed by **Neon**
serverless PostgreSQL. Cloud Run scales to zero (pay-per-use) and `asia-east1` is
in Taiwan (Changhua), so latency is excellent.

```mermaid
flowchart LR
    U[Browser] --> A[emp-api<br/>FastAPI + SPA on Cloud Run]
    A -->|DATABASE_URL / SSL| N[(Neon PostgreSQL)]
    B[Cloud Build] -->|image| AR[(Artifact Registry)]
    AR --> A
    AR --> D
    J[Cloud Run Jobs:<br/>migrate + seed] --> N
```

## Prerequisites

- `gcloud` CLI installed and authenticated: `gcloud auth login`
- A GCP project with **billing enabled**
- A [Neon](https://neon.tech) database. Use the `postgresql+psycopg://…` form of
  the connection string and keep `?sslmode=require` (pick a Neon region near
  `asia-east1`, e.g. Tokyo `ap-northeast-1` or Singapore `ap-southeast-1`).

## One-command deploy

The repo ships [`scripts/deploy_cloudrun.sh`](../scripts/deploy_cloudrun.sh),
which builds the image, runs migrations, deploys both services, and seeds data:

```bash
export PROJECT_ID="your-gcp-project"
export DATABASE_URL="postgresql+psycopg://user:pass@ep-xxx.aws.neon.tech/neondb?sslmode=require"
./scripts/deploy_cloudrun.sh
```

Optional overrides: `REGION` (default `asia-east1`), `REPO`, `IMAGE_TAG`,
`SEED` (default `true`).

At the end it prints the API/Swagger and SPA (`…/app/`) URLs.

## What the script does (step by step)

1. **Enable APIs** — Cloud Run, Cloud Build, Artifact Registry.
2. **Create an Artifact Registry** Docker repo (idempotent).
3. **Build & push** one image from the `Dockerfile` via Cloud Build.
4. **Migrate** — a one-off **Cloud Run Job** runs `alembic upgrade head` against
   Neon (kept out of the serving container to avoid start-up races).
5. **Deploy `emp-api`** — binds `$PORT`, `DATABASE_URL` set, public; also serves
   the static SPA at `/app`.
6. **Seed** — a one-off Cloud Run Job runs `python -m scripts.seed --reset`.

## Manual equivalent (if you prefer running commands yourself)

```bash
PROJECT_ID=your-project ; REGION=asia-east1 ; REPO=energy-matching
IMAGE="$REGION-docker.pkg.dev/$PROJECT_ID/$REPO/app:latest"
DATABASE_URL="postgresql+psycopg://...:...@.../db?sslmode=require"

gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com
gcloud artifacts repositories create $REPO --repository-format=docker --location=$REGION
gcloud builds submit --tag "$IMAGE"

gcloud run jobs deploy emp-migrate --image "$IMAGE" --region $REGION \
  --set-env-vars "DATABASE_URL=$DATABASE_URL" --command sh --args '-c,alembic upgrade head'
gcloud run jobs execute emp-migrate --region $REGION --wait

gcloud run deploy emp-api --image "$IMAGE" --region $REGION --allow-unauthenticated \
  --set-env-vars "DATABASE_URL=$DATABASE_URL,ENVIRONMENT=production" \
  --command sh --args '-c,uvicorn app.main:app --host 0.0.0.0 --port $PORT'

API_URL=$(gcloud run services describe emp-api --region $REGION --format 'value(status.url)')
echo "Web UI (SPA): $API_URL/app/"
```

## Notes & gotchas

- **`$PORT`** — Cloud Run injects it; both services must bind to it (the commands
  above do). It is passed literally so the container's `sh` expands it at runtime.
- **Secrets** — for production, prefer **Secret Manager** over `--set-env-vars`
  for `DATABASE_URL` (`--set-secrets DATABASE_URL=emp-db-url:latest`).
- **Cold starts** — scale-to-zero means the first request after idle is slower;
  set `--min-instances 1` on `emp-api` if you want it always warm (costs more).
- **Cost** — with scale-to-zero and low traffic this stays within a few cents;
  a demo often fits the Cloud Run free tier.
- **Region** — keep Cloud Run and Neon geographically close to cut latency.

See also the Render option in [`deployment.md`](deployment.md).
