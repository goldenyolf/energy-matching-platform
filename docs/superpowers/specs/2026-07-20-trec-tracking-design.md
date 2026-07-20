# T-REC 憑證追蹤 (Renewable Energy Certificate Tracking) Design

**Date:** 2026-07-20
**Status:** Approved (design)

## Goal

Track Taiwan Renewable Energy Certificates (T-REC; 1 憑證 = 1,000 度 = 1 MWh)
through a two-stage lifecycle: matching **issues + transfers** certificate batches
to customers (bundled with the 轉供), and customers **retire** batches to claim RE.
Persisted, with write operations. Status: `transferred` / `retired`.

## Data model

**New `app/models/trec.py`:**
```python
class TrecBatch(Base, TimestampMixin):
    __tablename__ = "trec_batches"
    id: int PK
    batch_no: str  # unique, indexed (e.g. TREC-2024-01-WF-CHANGFANG-CUST-TSMC)
    wind_farm_id: int  FK wind_farms.id, indexed
    customer_id: int   FK customers.id, indexed
    period: str        # "YYYY-MM" vintage, indexed
    quantity_mwh: float
    status: str        # "transferred" | "retired"  (plain String — no DB enum)
    wind_farm = relationship("WindFarm")   # one-directional (no back_populates)
    customer = relationship("Customer")
```
- `app/models/enums.py`: add `class TrecStatus(StrEnum): TRANSFERRED="transferred"; RETIRED="retired"` — value constants only; the column stays `String` to avoid the Postgres enum-migration pitfall.
- `app/models/__init__.py`: export `TrecBatch`, `TrecStatus`.

**Migration** (`down_revision = "0f179db933d6"`): `op.create_table("trec_batches", …)` with a unique index on `batch_no`, indexes on `wind_farm_id`/`customer_id`/`period`, FKs to wind_farms + customers. No enum type (String). Downgrade drops indexes + table.

## Service (`app/services/trec_service.py`)

- `issue_for_period(db, period) -> int` — **idempotent**. Runs
  `matching_service.compute_outcome(db, period)`; maps each contract allocation to
  `(wind_farm_id, customer_id)`; **aggregates** allocations by `(farm, customer)`;
  for each pair with quantity > 1e-9 and **no existing batch** for
  `(period, farm, customer)`, creates a `TrecBatch(status="transferred",
  quantity_mwh=sum, batch_no=f"TREC-{period}-{farm_code}-{cust_code}")`. Returns
  the number created.
- `retire(db, batch_id) -> TrecBatch` — `NotFoundError` if missing; sets
  `status="retired"` (idempotent if already retired).
- `get_ledger(db, period=None, customer_id=None) -> TrecLedger` — filtered batch
  list + summary, joined to farm/customer for codes.

## Schema (`app/schemas/trec.py`)

```python
class TrecBatchOut(BaseModel):
    id: int
    batch_no: str
    wind_farm_code: str
    wind_farm_name: str
    customer_code: str
    company_name: str
    period: str
    quantity_mwh: float
    status: str

class TrecSummary(BaseModel):
    total_batches: int
    total_quantity_mwh: float
    transferred_mwh: float
    retired_mwh: float
    transferred_batches: int
    retired_batches: int

class TrecLedger(BaseModel):
    period: str | None
    summary: TrecSummary
    batches: list[TrecBatchOut]     # newest first (id desc)
```

## Endpoints (`app/api/v1/trecs.py`, new router, prefix `/trecs`, registered in `router.py`)

```
GET  /api/v1/trecs?period=<YYYY-MM optional>&customer_id=<int optional>  → TrecLedger
POST /api/v1/trecs/issue?period=<YYYY-MM>                                → TrecLedger (after issuing)
POST /api/v1/trecs/{batch_id}/retire                                    → TrecBatchOut (updated)
```

## SPA (`web/`)

- `web/api.js`: add a `post(path, params)` helper (fetch `method:"POST"`, same
  error handling as `get`); methods `trecs(period, customerId)`,
  `trecsIssue(period)`, `trecRetire(batchId)`.
- `web/index.html`: nav under 監控/結算, after 轉供結算: `<a data-route="trecs">…T-REC 憑證</a>`.
- `web/app.js`: router `trecs: renderTrecs`; `renderTrecs`:
  - Controls: 期間 input + 「發行本期憑證」button (POST issue → reload) + optional customer filter.
  - KPI: 總憑證(MWh) · 已移轉(MWh) · 已註銷(MWh) · 批次數.
  - Ledger table: 批次號 · 風場 · 客戶 · 年份別 · 數量(MWh) · 狀態(pill: 已移轉 warnp / 已註銷 ok) · 動作(「註銷」btn for transferred rows → POST retire → reload).
  - Empty state: "本期尚無憑證,點『發行本期憑證』由媒合結果產生。"
  - Footnote: 1 憑證 = 1 MWh; 註銷後不可再交易. Data badge 示範資料.

## Seed

`scripts/seed.py` (sample path, after meters): call `trec_service.issue_for_period(db, "2024-01")` to populate the demo ledger, then retire a couple of batches (e.g. the first two) so both statuses show. Friendly line `T-REC 憑證   : 已由媒合結果發行`.

## Tests

- `tests/integration/test_trec.py` (service): issue_for_period creates batches
  from allocations, is idempotent (2nd run creates 0); retire flips status;
  summary totals consistent (transferred+retired == total).
- `tests/integration/test_trec_api.py`: GET ledger 200; POST issue creates
  batches; POST retire flips status; retire unknown id 404.
- `tests/integration/test_trec_model.py`: model persists + relationships resolve.
- Migration round-trips on SQLite (up/down/up).

## Gate

`ruff` · `black` · **`mypy app`** · `pytest` · `node --check`. Migration on SQLite
(CI) + Postgres (Neon). SSH push. Live: after deploy, POST issue (or re-seed) to
populate; live smoke.

## Out of scope

Standalone 發行 state (bundled with transfer here), certificate trading/market,
partial-batch retirement, external registry integration, per-1MWh serialization.
