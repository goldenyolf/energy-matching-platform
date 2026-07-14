# Deployment (Render + Neon Postgres)

This guide deploys the platform as **two Render web services** (API + Streamlit
dashboard) built from the repo's `Dockerfile`, backed by a **Neon** serverless
PostgreSQL database. Both platforms have a usable free tier.

> Why this combo: Streamlit is a persistent WebSocket service, so it needs a
> container/always-on host (not pure serverless). Render runs the Dockerfile
> directly; Neon gives a durable free Postgres that's just a connection string.

## Architecture on the cloud

```mermaid
flowchart LR
    U[Browser] -->|:443| D[emp-dashboard<br/>Streamlit on Render]
    U -->|:443| A[emp-api<br/>FastAPI on Render]
    D -->|API_BASE_URL<br/>server-side HTTP| A
    A -->|DATABASE_URL<br/>SSL| N[(Neon PostgreSQL)]
```

The dashboard calls the API **server-side** (Python `requests`), so there is no
browser CORS to configure.

## Prerequisites

- The repo pushed to GitHub (this project).
- A [Render](https://render.com) account (free).
- A [Neon](https://neon.tech) account (free).

## Step 1 — Create the database (Neon)

1. Neon → **New Project** → pick a region close to Render's `singapore`
   (e.g. AWS `ap-southeast-1`).
2. Copy the connection string. It looks like:
   ```
   postgresql://user:pass@ep-xxx.ap-southeast-1.aws.neon.tech/neondb?sslmode=require
   ```
3. **Change the scheme** so SQLAlchemy uses psycopg (keep `?sslmode=require`):
   ```
   postgresql+psycopg://user:pass@ep-xxx.ap-southeast-1.aws.neon.tech/neondb?sslmode=require
   ```
   Save this — it's your `DATABASE_URL`.

## Step 2 — Deploy the services (Render Blueprint)

1. Render → **New** → **Blueprint** → connect this GitHub repo.
2. Render reads [`render.yaml`](../render.yaml) and proposes two services:
   **emp-api** and **emp-dashboard**. Click **Apply**.
3. When prompted for the `sync: false` variables, set:
   - **emp-api** → `DATABASE_URL` = the Neon URL from Step 1.
   - **emp-dashboard** → `API_BASE_URL` = the API's URL, e.g.
     `https://emp-api.onrender.com` (visible on the emp-api service page).

On first boot, **emp-api** runs `alembic upgrade head` automatically, so the
schema is created in Neon.

## Step 3 — Seed demo data (once)

Open **emp-api** → **Shell** tab and run:

```bash
python -m scripts.seed --reset
```

(Or hit the API from your machine to create data via `POST /api/v1/...`.)

## Step 4 — Use it

- Dashboard → `https://emp-dashboard.onrender.com`
- API / Swagger → `https://emp-api.onrender.com/docs`
- Health → `https://emp-api.onrender.com/health`

## Notes & gotchas

- **Free-tier sleep:** free Render web services spin down after ~15 min idle;
  the first request then takes ~30 s (cold start). Warm it up before a demo.
- **Free-tier hours:** free web services share a monthly instance-hour budget.
  Two always-on services can exhaust it — sleeping when idle keeps you within it.
- **SSL:** Neon requires SSL; keep `?sslmode=require` in the URL.
- **Secrets:** `DATABASE_URL` is set in the Render dashboard (marked `sync:false`),
  never committed. `.env` stays git-ignored.
- **Migrations on deploy:** every deploy re-runs `alembic upgrade head` (safe/idempotent).
- **Region:** keep Render and Neon in matching regions (both `singapore`/`ap-southeast-1`)
  to minimise latency.

## Alternatives

- **Render-managed Postgres** instead of Neon: uncomment the `databases:` block
  and the `fromDatabase` env var in `render.yaml`. (Render's free Postgres is
  deleted after 90 days — Neon is better for a durable demo.)
- **Google Cloud Run + Cloud SQL / Neon:** deploy the same Dockerfile as two
  Cloud Run services (scale-to-zero, pay-per-use). Set `--port` to `$PORT`, add
  the Cloud SQL connector or use Neon over SSL, and run `alembic upgrade head`
  as a pre-deploy step or Cloud Run Job.
- **Streamlit Community Cloud (dashboard only) + Render (API):** free Streamlit
  hosting for the dashboard, with `API_BASE_URL` pointing at the Render API.
