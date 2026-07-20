# 多電號/雙廠區 (Multi-meter / Multi-site) Design

**Date:** 2026-07-20
**Status:** Approved (design)

## Goal

Model a customer's consumption as multiple **電號/廠區 (meters/sites)**, each with
its own consumption and RE target, and show per-meter RE attainment — the core
matching stays customer-level; the customer's green is distributed across its
meters with a **target-priority** policy so each site shows a distinct RE%.
Aligns with the user's dual-site (雙廠區) patent.

## Scope (lightweight analysis layer)

- Meters are a **demand-side sub-unit of a customer**. Contracts stay
  customer-level; only consumption is attributable to a meter.
- Core matching / settlement / optimization are **unchanged** (a customer's
  total consumption still drives them; meters just partition that total).
- New per-meter breakdown endpoint + SPA page.

## Data model

**New `app/models/meter.py`:**
```python
class Meter(Base, TimestampMixin):
    __tablename__ = "meters"
    id: int PK
    code: str  # 電號, unique, indexed
    customer_id: int  FK customers.id, indexed
    name: str  # 廠區名
    location: str | None
    re_target_percent: float = 0.0
    annual_consumption_mwh: float | None  # used to weight the demo consumption split
    customer: relationship(back_populates="meters")
```
- `Customer`: add `meters: relationship(back_populates="customer", cascade="all, delete-orphan")`.
- `ConsumptionData`: add `meter_id: Mapped[int | None]` FK `meters.id`, nullable,
  indexed, default None (rows without a meter stay customer-level → back-compat).

**Migration** (`alembic revision`, down_revision = `2440c428ccf6`):
- `op.create_table("meters", ...)` with the columns above + FK to customers.
- Add `meter_id` to `consumption_data` via `op.batch_alter_table` (SQLite-safe):
  `batch.add_column(sa.Column("meter_id", sa.Integer(), nullable=True))` and a
  named FK `batch.create_foreign_key("fk_consumption_meter", "meters", ["meter_id"], ["id"])`.
- Downgrade drops the column then the table.

## Green distribution (target-priority greedy — analysis layer only)

For customer + period:
1. `total_green` ← `compute_customer_optimization(db, customer_id, period).buyer.green_mwh` (DRY).
2. Per meter `cons[m]` = Σ `ConsumptionData.consumed_energy_mwh` where `meter_id == m.id` in the period.
3. `target_energy[m] = cons[m] * re_target[m] / 100`.
4. **Target pass** — meters sorted by `re_target_percent` desc (tie: code asc):
   `give[m] = min(remaining, target_energy[m])`, `remaining -= give[m]`.
5. **Leftover pass** — if `remaining > 1e-9`, meters sorted by `cons` desc: top up
   `give[m] += min(cons[m] - give[m], remaining)`, `remaining -= …`, until spent.
6. Per meter: `allocated = give[m]`, `re_percent = allocated / cons * 100` (0 if cons 0),
   `target_met = re_percent + 1e-9 >= re_target and re_target > 0`.
- **Consistency:** `Σ allocated == min(total_green, Σ cons)` (== `total_green` when
  the customer is fully metered). This is asserted in tests.

## Schema (`app/schemas/meter.py`)

```python
class MeterRow(BaseModel):
    meter_id: int
    code: str
    name: str
    location: str | None
    consumption_mwh: float
    allocated_green_mwh: float
    re_percent: float
    re_target_percent: float
    target_met: bool

class MeterBreakdown(BaseModel):
    customer_id: int
    customer_code: str
    company_name: str
    period: str
    meter_count: int
    total_consumption_mwh: float
    total_green_mwh: float
    customer_re_percent: float
    meters_meeting_target: int
    meters: list[MeterRow]     # sorted by re_target desc
```

## Service (`app/services/meter_service.py`)

`compute_meter_breakdown(db, customer_id, period) -> MeterBreakdown`
- Loads the customer (404 via the shared optimization path if unknown) and its meters.
- If the customer has **no meters**, returns `meters=[]`, `meter_count=0` (the SPA
  shows a "no meters" hint); still fills customer totals from the optimization result.
- Otherwise runs the distribution above and builds rows.

## Endpoint (`app/api/v1/analytics.py`)

```
GET /api/v1/analytics/meter-breakdown?customer_id=<int, ge=1>&period=<YYYY-MM>
→ MeterBreakdown
```

## SPA (`web/`)

- `web/api.js`: `meterBreakdown(customerId, period)`.
- `web/index.html`: nav item **under 資料管理**, after 企業客戶:
  `<a data-route="meters">…多電號</a>`.
- `web/app.js`: router `meters: renderMeters`; `renderMeters` (customer + period
  form, like evaluate) → `renderMeterBreakdown`:
  - KPI: 電號數 · 客戶總用電 · 客戶總 RE% · 達標電號數.
  - Table: 電號(code) · 廠區(name/location) · 用電(MWh) · 分配綠電(MWh) · RE%(reCell) · 目標 · 達標(metPill).
  - No-meters state: a placeholder card "此客戶尚未設定多電號/廠區資料".
  - Footnote: distribution policy note. Data badge shows 示範資料 by route.

## Seed / demo data

- New `data/sample/meters.csv`: `customer_code,code,name,location,re_target_percent,annual_consumption_mwh`.
  - **CUST-TSMC → 台南廠 (TSMC-TN, target 90), 高雄廠 (TSMC-KH, target 60)** — the dual-site case.
  - **CUST-AUO → 3 meters** (e.g. 龍潭/台中/後里) with varied targets — a three-site case.
- New `scripts/generate_meter_profiles.py` with `split_consumption_to_meters(db)`:
  for each customer that has meters, split every one of its `ConsumptionData` rows
  (meter_id None) into per-meter rows weighted by `annual_consumption_mwh` share,
  set `meter_id`, preserve `time_slot`/`period`, delete the original. Idempotent
  (skips rows already having a meter_id). Deterministic; last meter absorbs rounding.
- `scripts/seed.py`: after `split_profiles`, also import meters (new
  `csv_importer.import_meters`) and call `split_consumption_to_meters` for the
  sample source. Friendly progress line (e.g. `電號拆分      : …`).

## Tests

- `tests/integration/test_meter.py` (service): a customer with 2 meters (targets
  90 / 40), known consumption + a `compute_customer_optimization`-driven green;
  assert target-priority order (high-target meter filled first), `Σ allocated ==
  total_green`, per-meter `re_percent`/`target_met`. A no-meters customer → empty.
- `tests/integration/test_meter_api.py`: 200, totals consistent, unknown customer 404.
- `tests/integration/test_meter_profiles.py`: `split_consumption_to_meters`
  splits by share, sums preserved per period/slot, idempotent.

## Gate

`ruff` · `black` · **`mypy app`** · `pytest` · `node --check`. Migration must run
on SQLite (CI) and Postgres (Neon). SSH push. Live smoke + re-seed note after deploy.

## Out of scope

Per-meter contracts / per-meter matching (that is the heavy "逐電號媒合" variant),
meter-level settlement bills, editing meters via the UI.
