# 合約風險告警 (Contract Risk Alerts) Design

**Date:** 2026-07-20
**Status:** Approved (design)

## Goal

Scan all contracts and produce a **severity-ranked list of risk alerts** across
four categories, on a dedicated SPA page. Lightweight — no data-model change; a
projection over contracts + the existing matching outcome.

## Risk rules

Reference date `ref` (defaults to `date.today()`, overridable for tests).
`horizon_months` default 6. Period `P` drives the matching-based rule.

| # | Category (`category`) | Condition | Severity |
|---|---|---|---|
| 1 | `expiry` 合約即將到期 | `status == active` and `ref <= end_date <= ref + horizon_months` | ≤1 mo → high; ≤3 mo → medium; else low |
| 2 | `under_delivery` 供電不足 | active contract in period P: `delivered < expected_cap × (1 − 0.05)` and `expected_cap > 0` | shortfall% ≥50 → high; ≥20 → medium; else low |
| 3 | `over_commitment` 風場超額承諾 | per farm, Σ active `contracted_percentage` > 100 | >120 → high; else medium |
| 4 | `status_mismatch` 狀態不一致 | (`end_date < ref` and `status == active`) or (`start_date <= ref` and `status == pending`) | medium |

- **`expected_cap`** (rule 2) per active contract = the tighter of its caps:
  `contracted_energy_mwh` (if set) and `contracted_percentage/100 × farm_generation_P`
  (if set); `delivered` = the contract's `allocated_mwh` from `compute_outcome`.
  `shortfall% = (expected_cap − delivered) / expected_cap × 100`. Skipped
  contracts (allocated 0) surface here as high.
- Severity order for sorting/counts: high > medium > low.

## Data source (DRY)

- Rule 2 reuses `app.services.matching_service.compute_outcome(db, P)` →
  `outcome.allocations` (`contract_id`, `allocated_mwh`) and `outcome.farm_summaries`
  (`farm_id`, `generated_mwh`) and `outcome.skipped`.
- Rules 1/3/4 are plain queries over `Contract` (+ `WindFarm`/`Customer` codes for
  labels). No new matching.

## Schema (`app/schemas/risk.py`)

```python
class RiskAlert(BaseModel):
    severity: str                     # "high" | "medium" | "low"
    category: str                     # expiry | under_delivery | over_commitment | status_mismatch
    contract_number: str | None
    wind_farm_code: str | None
    customer_code: str | None
    title: str
    detail: str
    suggested_action: str

class RiskCounts(BaseModel):
    high: int
    medium: int
    low: int
    total: int

class RiskReport(BaseModel):
    period: str
    reference_date: str               # ISO date
    horizon_months: int
    counts: RiskCounts
    alerts: list[RiskAlert]           # sorted high→low, then category
```

## Service (`app/services/risk_service.py`)

`compute_contract_risks(db, period, *, reference_date: date, horizon_months: int) -> RiskReport`

- Loads active/all contracts with farm + customer codes.
- Builds alerts per the four rules; each carries a zh-TW `title`, `detail`
  (concrete numbers/dates), and `suggested_action`.
- Sorts alerts by severity rank (high=0, medium=1, low=2) then category; fills
  `counts`.
- `_SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2}`.

## Endpoint (`app/api/v1/analytics.py`)

```
GET /api/v1/analytics/contract-risks?period=<YYYY-MM>&horizon_months=<int, optional, default 6>
→ RiskReport
```

`reference_date` is `date.today()` (not a query param; deterministic override is
service-level, used by tests).

## SPA (`web/`)

- `web/api.js`: `contractRisks(period, horizonMonths)`.
- `web/index.html`: new nav item under 監控/結算 — `<a data-route="risks">…風險告警</a>`.
- `web/app.js`:
  - router `views`: `risks: renderRisks`.
  - `renderRisks()` — form (期間 + 到期月數) → `api.contractRisks` → render.
  - Render: KPI strip (高/中/低/總 counts, colored via pos/neg/prem) + a table
    (嚴重度 chip · 類型 · 影響對象〔合約/風場/客戶〕· 說明 · 建議動作). Severity chip
    reuses `pill` styles: high→a red-ish pill, medium→warnp, low→ok/neutral. Add a
    `.pill.bad` style (red) for high.
  - Data badge already shows 示範資料 by route — no extra wiring.

## Severity chip styling

Add to `web/styles.css`: `.pill.bad{background:var(--bad-soft);color:var(--bad)}`
(high). Medium reuses `.pill.warnp`; low reuses `.pill.ok`.

## Demo data (so each risk is visible)

Edit `data/sample/contracts.csv` so the sample scenario triggers every rule:
- `PPA-TPC-005`: `end_date` → `2026-08-10` (expiry **high**, ~<1 mo from ref).
- `PPA-TPC-006`: `end_date` → `2026-10-15` (expiry **medium**) **and**
  `contracted_percentage` 15 → 55 (with PPA-TPC-001's 60 on the same farm
  TPC-CHANGGONG → Σ 115% → over-commitment **medium**; priority-3 → squeezed →
  under-delivery).
- `PPA-TPC-008`: `end_date` → `2026-03-31`, keep `status = active`
  (status_mismatch: expired-but-active, **medium**).

**Live demo:** the deployed DB was seeded once (no seed-on-deploy). To reflect
these tweaks live, re-seed once via the Render service Shell:
`python -m scripts.seed --reset --source sample` (runs where DATABASE_URL is
already in the env — no secret in local shell). Non-blocking for the feature.

## Tests (`tests/integration/test_risk.py`, `test_risk_api.py`)

- One trigger case per rule (unit, via `compute_contract_risks` with a fixed
  `reference_date`): expiry (contract ending in ~2 mo → medium); under-delivery
  (two contracts on one farm, low-priority squeezed); over-commitment (Σ% 130 →
  high); status_mismatch (active with past end_date).
- No-risk case → empty alerts, zero counts.
- Endpoint (integration): 200, counts consistent with `len(alerts)`.

## Gate

Full local gate: `ruff` · `black` · **`mypy app`** · `pytest` · `node --check`.
SSH push. Live smoke after deploy.

## Out of scope

Email/push notifications, alert acknowledgement/persistence, configurable
thresholds per customer, forecast-based (future under-delivery) alerts.
