# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/), and this project adheres to
[Semantic Versioning](https://semver.org/).

## [0.2.0] — 2026-07-14

### Added — Energy Matching Platform MVP
- Domain entities: wind farms, customers, contracts (PPA), generation &
  consumption data, matching runs & results (SQLAlchemy 2.x).
- Pure, deterministic monthly **matching engine** with priority ordering,
  contract caps, no over-allocation / over-consumption, and auditable reasons.
- **REST API** (FastAPI): CRUD for core entities, CSV import for generation &
  consumption, matching runs, and analytics endpoints — with schemas, validation,
  status codes and domain-error handling.
- **RE-target analytics**: per-customer coverage/gap/target-met, per-farm
  utilisation, per-period summaries.
- Pluggable **ingestion**: CSV importer, `DataSource` interface, deterministic
  `MockDataGenerator`, `PublicDataAdapter` placeholder (Phase 2).
- **Streamlit dashboard**: Overview, Wind Farms, Customers, Contracts, Matching.
- **Infrastructure**: Alembic migrations, Dockerfile, Docker Compose (Postgres +
  API + dashboard), Makefile, `.env.example`, pre-commit, GitHub Actions CI.
- **Tests**: unit tests for the engine + integration tests for the service and
  API; coverage on the matching core ≥ 80 % (currently ~97 %).
- **Docs**: architecture, domain model (ERD), matching rules (flow), roadmap,
  assumptions — with Mermaid diagrams.

## [0.1.0] — 2026-07-14 (tag `v0.1-mvp`)

- Initial proportional-allocation MVP: matching + FastAPI + self-contained HTML
  dashboard. Superseded by 0.2.0; preserved under the `v0.1-mvp` git tag.
