# Deployment (Render + Neon Postgres)

This guide deploys the platform as **a single Render web service** (the FastAPI
app, which also serves the static SPA at `/app`) built from the repo's
`Dockerfile`, backed by a **Neon** serverless PostgreSQL database. Both have a
usable free tier.

> Why this combo: Render runs the Dockerfile directly; Neon gives a durable free
> Postgres that's just a connection string. The SPA is static files served
> same-origin by the API, so there's no separate frontend service and no CORS.

## Architecture on the cloud

```mermaid
flowchart LR
    U[Browser] -->|:443| A[emp-api<br/>FastAPI + SPA on Render]
    A -->|DATABASE_URL<br/>SSL| N[(Neon PostgreSQL)]
```

The SPA is served same-origin by the API (`/app`), so there is no separate
frontend service and no browser CORS to configure.

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

   > ⚠️ **Use Neon's DIRECT endpoint, not the pooled one.** If your string has
   > `-pooler` in the host, **remove it**
   > (`ep-xxx-pooler.c-3...` → `ep-xxx.c-3...`). Render's free network connects by
   > resolved IP, which drops the SNI hostname Neon's pooler needs to route your
   > project — the pooled URL then fails with `database "neondb" does not exist`.
   > The direct endpoint is fine for this demo's load. (Also avoid
   > `options=endpoint%3D...`: the `%` breaks Alembic's ini parser.)

## Step 2 — Deploy the services (Render Blueprint)

1. Render → **New** → **Blueprint** → connect this GitHub repo.
2. Render reads [`render.yaml`](../render.yaml) and proposes the **emp-api**
   service. Click **Apply**.
3. When prompted for the `sync: false` variable, set:
   - **emp-api** → `DATABASE_URL` = the Neon **direct** URL from Step 1.

On first boot, **emp-api** runs `alembic upgrade head` automatically, so the
schema is created in Neon.

## Step 3 — Migrate + seed demo data (once)

Quickest path — run from **your machine** against the Neon URL. This both
verifies the migrations on real Postgres and loads the demo + time-slot data:

```bash
export DATABASE_URL="postgresql+psycopg://user:pass@ep-xxx.../neondb?sslmode=require"
alembic upgrade head                      # create schema (idempotent; Render also runs this on boot)
python -m scripts.seed --reset            # demo: 3 farms, 5 customers, 8 contracts, 12 months
python -m scripts.generate_slot_profiles  # split monthly into peak/half/off-peak (needed for the SPA time-slot panel)
```

Alternatively use **emp-api → Shell** on Render (schema is already migrated on
boot): `python -m scripts.seed --reset && python -m scripts.generate_slot_profiles`.

## Step 4 — Use it

- **Web UI (SPA)** → `https://emp-api.onrender.com/app/` ← the whole product UI, served by the API
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
