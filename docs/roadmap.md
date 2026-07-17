# Roadmap

## Phase 1 — MVP (this release)

- Core entities: wind farms, customers, contracts, generation, consumption.
- Deterministic monthly green-energy matching engine with auditable reasons.
- RE-target analytics (coverage, gap, target met) per customer / farm / period.
- REST API (FastAPI + Swagger) with request/response schemas and error handling.
- CSV import + replaceable `DataSource` interface + deterministic mock generator.
- One-click seed with a rich demo scenario (under/over-supply, priorities, etc.).
- Web UI: a dependency-free static SPA (`web/`) served by the API at `/app` —
  overview, farms, customers, contracts, optimization evaluation, live renewables.
- Alembic migrations, Docker Compose, Makefile, pre-commit, CI, tests (≥80 % on
  the matching core).

## Phase 2 — Public data & data quality

- Real public open-data **adapter** (only against a documented, legal API,
  honouring ToS / robots.txt / rate limits).
- Scheduled ingestion jobs and incremental updates.
- Data-quality checks (gaps, outliers, unit sanity, duplicate detection).
- Hourly (8760) generation & consumption profiles for **time-based matching**.
- Simple generation/consumption forecasting.

## Phase 3 — Optimisation & portfolio

- Replace greedy priority allocation with a **linear-programming optimiser**
  that minimises total RE gap or cost under the same constraints.
- Multi-source green-energy portfolios (blend farms per customer).
- Price and risk analysis; scenario comparison.
- Certificate (T-REC) tracking and retirement modelling.

## Phase 4 — Intelligence

- AI assistant with natural-language querying over the data model.
- Contract-risk alerts (expiry, under-delivery, over-commitment).
- RE-target recommendations (which contracts/farms close a customer's gap).
