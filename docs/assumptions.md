# Assumptions & scope

This document records the deliberate modelling choices and limits of the MVP.

## Data

- **All demo data is simulated.** Wind-farm names are inspired by public Taiwan
  offshore-wind information, but every figure (capacity, generation, consumption,
  contract terms) is illustrative and **not** a real contract or grid reading.
- **No live scraping.** The platform ships CSV import + a deterministic
  `MockDataGenerator`. A real `PublicDataAdapter` is a Phase-2 placeholder and,
  when built, must respect the source's Terms of Service, authentication,
  robots.txt and rate limits. The project never bypasses access controls.

## Matching model

- **Period = one calendar month.** Generation/consumption are aggregated to the
  month; there is no intra-month (hourly) matching in Phase 1.
- **`contracted_energy_mwh` is a monthly cap.** For an MVP with monthly periods,
  a contract's fixed volume is interpreted as its per-month allocatable ceiling.
- **`contracted_percentage` is a share of that farm's monthly generation.**
- When both caps are present, the **tighter** one applies.
- **Only `active`, in-window contracts allocate.** Status and the
  `[start_date, end_date]` window are both enforced.
- **Greedy by priority**, not a global optimum (see roadmap Phase 3).
- **Floating-point energy** with rounding to 6 decimals; comparisons use a small
  epsilon. Deterministic given a fixed contract ordering.

## Technical

- **Database:** SQLite by default for zero-config local dev and tests;
  PostgreSQL for Docker/production. Models are kept DB-agnostic so both work.
- **Local Python:** the repo targets **Python 3.12**. `uv` is preferred for
  environment management; `pip` is a documented fallback.
- **RE target** (`re_target_percent`, `target_year`) is treated as an annual goal;
  monthly `achieved_re_percent` and `gap_to_target_mwh` are computed per period
  as a proxy for progress.

## Not in scope (this is a portfolio MVP)

- It is **not** a settlement, certificate-transfer, or trading system.
- No authentication/authorisation, multi-tenancy, or audit trail beyond
  matching-run records.
- No official affiliation with Taipower, TSEC, or any energy company.
