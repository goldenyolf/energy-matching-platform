# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/), and this project adheres to
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- **合約詳情頁（商務視角）** — 合約清單每一列可點入 `#/contract?id=&year=`，看該紙合約整年的逐月履約與雙面帳。
  - **全年被什麼卡住**：12 格分佈條標出每個月的綁定約束（合約上限／案場供給／客戶用電／未生效），並產生一句有成立條件的結論——「有加購空間」只在案場尚有餘電且客戶仍有未滿足用電時才會出現。
  - **月別履約圖**：柱為實際分配、短橫為月上限、虛線短橫為 take-or-pay 門檻；點任一月展開明細，含引擎原文的分配理由。
  - **雙面帳**：買方應付、案場應收、售電業毛利同頁分欄，公式沿用轉供結算單，並註明本頁為履約基準（合約優先序引擎）、與結算單的最佳化基準會有落差。
  - 新增唯讀端點 `GET /api/v1/analytics/contract-detail?contract_id=&year=`。
  - 未設售電價的合約不顯示金額而非以躉售價代入；未設上限的合約使用率顯示「未設上限」而非 0%。

## [0.3.0] — 2026-07-30

Everything between the MVP and today, backfilled in one entry: no releases were
cut in between, so no intermediate version numbers are invented here.

### Added — Matching & optimisation
- **MILP economic optimiser** (PuLP + CBC) over the monthly period: maximise
  retailer margin under RE-target and structural constraints, three-stage
  lexicographic solve, minimum-allocation and minimum-site-count constraints.
- **Time-slot (TOU) matching** on Taipower's three-band tariff: per-slot greedy
  matcher, a joint per-slot MILP with secondary matching, seasonal grey-price
  helpers, and a deterministic monthly→slot profile generator. Slot rows replace
  the monthly row, so the two never double-count.
- **Many-to-many scenario explorer (what-if)**: greenfield optimisation across
  freely chosen sites and customers with per-site feed-in overrides and
  per-customer RE targets, rendered as a Sankey-style flow map.
- **Unified per-customer evaluation**: one endpoint produces the seller's margin
  and the buyer's RE attainment/cost from a single solve, so both sides of the
  page can never disagree.

### Added — Hourly 24/7 CFE matching
- **Time-coincident hourly engine**: only generation and load overlapping within
  the same hour counts. Surplus and shortfall never cross an hour boundary, and
  CFE% is reported against the "paper" monthly-netting figure so time mismatch
  is explicit.
- **Typical-day curve modeller** for periods without real interval data (wind
  season × time-of-day, industry-specific load shapes), with Σhourly == the
  original monthly total so it still reconciles.
- **Real 15-minute interval pipeline** (`interval_readings`): when present it
  replaces the modelled curves in place and unlocks the hour × day CFE heatmap.
- **Hourly matching view** with the 24-hour supply/demand chart, per-customer
  drill-down, data-source badge and the heatmap.

### Added — Wind-solar complementarity
- Solar joins as a generating asset on the existing site table
  (`farm_type="solar"`) — no new table, and **the matching engine is unchanged**.
  Technology-aware daily shape (midday bell), monthly seasonality (summer-strong,
  the mirror of wind), time-slot split and interval synthesis.
- **Wind-only vs wind+solar comparison**: the same load re-matched with solar
  assets and their contracts removed, reported system-wide and per customer.

### Added — Storage time-shifting
- **Customer-side batteries** (`batteries`) with capacity, power, round-trip
  efficiency and initial SOC, plus CRUD endpoints.
- **Greedy time-sequential charge/discharge layer** built on top of the hourly
  engine's output rather than inside it, so the engine's no-carry-over invariant
  stays intact. Discharge-first, two-round charge priority (own-contract sites
  first), per-farm charge attribution, SOC continuous across days.
- **No-storage vs with-storage comparison**, so the headline reads as three
  segments — wind only → wind+solar → wind+solar+storage — each adding exactly
  one thing, system-wide and per customer.
- Generation now decomposes into three mutually exclusive buckets — delivered
  directly, charged into a battery, spilled — so the spill figure can no longer
  absorb energy that went into a battery and never came out.

### Added — Settlement, certificates & contracts
- **Transfer settlement bill**: per-slot green/grey volumes and amounts,
  wheeling fees, retailer margin, avoided carbon, and take-or-pay shortfall.
- **T-REC certificate ledger** with the issue → transfer → retire lifecycle.
- **Contract depth**: annual volume with a monthly allocation shape, take-or-pay
  floor, and CPI price escalation.

### Added — Analysis & monitoring
- **Investment analysis**: per-site and portfolio CAPEX, ROI and static payback,
  with actual/P50/P90 generation scenarios.
- **RE-target recommendations**: cheapest-first suggestions for closing a
  customer's gap, marked as contract extension or new signing.
- **Contract risk alerts** across five categories, graded by severity.
- **Multi-meter (電號/廠區)** breakdown with per-site RE targets and
  target-priority distribution.
- **Live Taipower renewables** — the one real data source, read-through only,
  with per-site detail and source links.

### Added — Data & ingestion
- CSV import for sites, customers, contracts, generation, consumption and meters,
  with per-row error feedback; full CRUD for the core entities.
- Wind-farm engineering attributes (type, capacity factor P50/P90, turbine count,
  grid voltage) driving expected-vs-actual generation.
- Taipower open-data wind source with a rolling recent-months window, plus demo
  contracts and demand aligned to its generation window.

### Added — Frontend & docs
- **Zero-dependency static SPA** served by the API at `/app/`, covering every
  page, with full mobile RWD, theme persistence, toasts, click-to-open info
  popovers for the confusing fields, and a context-aware data-provenance badge.
- Product explainer page with an interactive "why hourly matching matters"
  section, a roadmap board and a drag-and-drop task board.

### Added — Deployment & engineering
- Render blueprint and Docker image serving API + SPA, with start scripts and
  `SEED_ON_START` / `SEED_RESET` for shell-less demo seeding.
- CI coverage gate at 90% over `app`, plus SPA-serving smoke tests.

### Changed
- **Retired the Streamlit dashboard** — the static SPA is the only frontend.
- Navigation consolidated into segmented sub-tabs; CRUD is always on rather than
  behind an edit toggle.
- UI fully localised to Traditional Chinese.
- Demo customers anonymised.
- **Breaking:** the Taipower ingestion import window changed to a rolling
  recent-N-months window.

### Fixed
- Postgres `CREATE TYPE` trap on managed deploys: enum-column migrations now
  create and drop their type explicitly (time slot, customer green target).
- `DATABASE_URL` normalised to the psycopg v3 driver, so a bare `postgresql://`
  no longer crashes the deploy.
- Render deployment: start scripts for `dockerCommand` (status 127), and the
  SPA actually copied into the image.
- N+1 query in the meter breakdown, now one grouped query.
- Scenario allocation capped at each customer's RE target.
- Storage accounting: per-customer uplift no longer double-counts the storage
  gain, segment labels derive from what is actually present rather than array
  length, and deleting a customer now cascades to its batteries.
- Optimiser determinism covers reordered inputs; RE-target tolerance corrected.
- Assorted UI fixes: overview table clipping, oversized icons, field alignment,
  loading and period-memory behaviour.

### Security
- Write gate (`ADMIN_WRITE_TOKEN`) on create/update/delete/import endpoints, with
  constant-time comparison and delete protection for referenced records.
- Per-IP rate limiting, bounded MILP solve time with a concurrency semaphore, and
  a 10 MB upload cap.
- Removed a destructive seeding foot-gun; `SEED_ON_START` is non-destructive and
  only the explicit `SEED_RESET` rebuilds the database.

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
