# P5 — 轉供結算帳單 (Transfer Settlement Bill) Design

**Date:** 2026-07-20
**Status:** Approved (design)

## Goal

Produce a formal, two-sided **transfer settlement bill (轉供結算單)** for a chosen
customer and period, derived from the existing per-slot matching engine, adding a
Taipower wheeling fee and a carbon-reduction figure. Presented as a formal
invoice-style page in the SPA.

## Non-goals

- No PDF export, no payment/accounting integration, no persistence of bills
  (computed on-the-fly like every other analytics endpoint).
- No new matching logic — the bill is a *projection* of the existing
  `compute_customer_optimization` result.
- Grey (灰電) shortfall is shown **for reference only**; it is not part of
  「客戶應付」 (that is Taipower's own retail bill, outside 轉供).

## Perspective & granularity

- **Two-sided** (售電業 in the middle): the bill shows what the customer pays,
  what the farm(s) receive, and the retailer's margin.
- **Per-time-slot (TOU)**: 尖峰 / 半尖峰 / 離峰, reusing the P4b slot breakdown.

## Data source (DRY — no new matching)

Reuse `app.services.customer_optimization_service.compute_customer_optimization(
db, customer_id, period, opts)` → `CustomerOptimizationResult`. Fields consumed:

- `seller.sales_revenue` — 客戶綠電轉供費 (green MWh × transfer price)
- `seller.procurement_cost` — 風場應收 (green MWh × feed-in/PPA)
- `seller.gross_profit` — retailer margin before wheeling
- `buyer.green_mwh`, `buyer.grey_mwh`, `buyer.total_consumption_mwh`, `buyer.re_percent`
- `slot_breakdown[]` — `{slot, grey_price_per_kwh, consumption_mwh, allocated_mwh, re_percent}`
- `allocations[]` — per-farm `{wind_farm_code, wind_farm_name, allocated_mwh, contract_number}` (for the 用電戶 ↔ 風場 header)
- `transfer_price_used` — single transfer (轉供) price, may be `None`
- `season`, `period`, `solver_status`

## Economics

Constants: `_KWH = 1000`.

Per slot `s` in `slot_breakdown`:
- `green_mwh = s.allocated_mwh`
- `transfer_price = transfer_price_used` (fallback: `sales_revenue / (green_mwh × _KWH)` when None and green > 0, else 0)
- `green_cost = green_mwh × _KWH × transfer_price`
- `grey_mwh = max(0, s.consumption_mwh − s.allocated_mwh)`
- `grey_cost = grey_mwh × _KWH × s.grey_price_per_kwh`

Totals:
- `green_transfer_cost = seller.sales_revenue` (== Σ slot green_cost — consistency check)
- `wheeling_fee = buyer.green_mwh × _KWH × wheeling_fee_per_kwh`
- `grey_cost_total = Σ slot grey_cost`  (reference only)
- `customer_payable = green_transfer_cost + wheeling_fee`
- `farm_receivable = seller.procurement_cost`
- `retailer_margin = green_transfer_cost − farm_receivable − wheeling_fee` (= `gross_profit − wheeling_fee`)
- `retailer_margin_percent = retailer_margin / customer_payable × 100` (0 when payable == 0)
- `carbon_avoided_tco2e = buyer.green_mwh × grid_emission_factor_kg_per_kwh`
  (green_kWh × kg/kWh ÷ 1000 → tonnes; green_mwh × 1000 × f ÷ 1000 = green_mwh × f)

## New config (`app/core/config.py`)

- `wheeling_fee_per_kwh: float = 0.1` — NTD/kWh Taipower 轉供/輸配 service fee (illustrative demo default)
- `grid_emission_factor_kg_per_kwh: float = 0.494` — Taiwan 2023 grid electricity emission factor (kgCO₂e/kWh)

## Schema (`app/schemas/settlement.py`)

```python
class SettlementSlotRow(BaseModel):
    slot: str
    green_mwh: float
    transfer_price_per_kwh: float
    green_cost: float
    grey_mwh: float
    grey_price_per_kwh: float
    grey_cost: float

class SettlementParty(BaseModel):
    wind_farm_code: str
    wind_farm_name: str
    allocated_mwh: float
    contract_number: str

class SettlementTotals(BaseModel):
    green_mwh: float
    grey_mwh: float
    green_transfer_cost: float
    wheeling_fee: float
    grey_cost: float
    customer_payable: float
    farm_receivable: float
    retailer_margin: float
    retailer_margin_percent: float
    carbon_avoided_tco2e: float

class SettlementResult(BaseModel):
    period: str
    season: str
    solver_status: str
    customer_id: int
    customer_code: str
    company_name: str
    transfer_price_per_kwh: float
    wheeling_fee_per_kwh: float
    grid_emission_factor_kg_per_kwh: float
    farms: list[SettlementParty]        # 供電風場(用於抬頭 用電戶 ↔ 風場)
    slots: list[SettlementSlotRow]
    totals: SettlementTotals
```

## Service (`app/services/settlement_service.py`)

`compute_settlement(db, customer_id, period, opts: SettlementOptions) -> SettlementResult`

- `SettlementOptions` carries `transfer_price_per_kwh: float | None`,
  `wheeling_fee_per_kwh: float | None` (None → config defaults).
- Calls `compute_customer_optimization` with a `CustomerOptimizeOptions` built from
  the transfer-price override (min-sites / min-% left at config defaults).
- Maps the result into `SettlementResult` per the economics above.
- Raises the same 404 as customer-optimization for an unknown customer (delegated).

## Endpoint (`app/api/v1/analytics.py`)

```
GET /api/v1/analytics/settlement
    ?customer_id=<int, ge=1>
    &period=<YYYY-MM>
    &transfer_price_per_kwh=<float, ge=0, optional>
    &wheeling_fee_per_kwh=<float, ge=0, optional>
→ SettlementResult
```

## SPA (`web/`)

- `web/api.js`: add `settlement(customerId, period, transferPrice, wheelingFee)`.
- `web/index.html`: turn the disabled 轉供結算 nav item into
  `<a data-route="settlement">…轉供結算</a>` (drop the `off` class and P5 tag).
- `web/app.js`:
  - Register `settlement: renderSettlement` in the router `views` map.
  - `renderSettlement()` — a form (用電戶 select + 期間 + optional 轉供價 / 輸配費)
    like `renderEvaluate`; on submit calls `api.settlement(...)` and renders a
    formal **bill** via `renderSettlementBill(root, r)`.
  - `renderSettlementBill` — an invoice-style card: header (期間, 用電戶 ↔ 供電風場),
    a per-slot 明細 table (時段 / 綠電量 / 轉供價 / 綠電金額 / 灰電量 / 灰電TOU價 / 灰電金額),
    a totals block (綠電轉供費, 台電輸配費, 客戶應付合計, 風場應收, 售電業毛利 + 毛利率,
    灰電補足〔參考〕), and a 減碳量 highlight (tCO₂e).
  - The topbar data badge already reads the route → shows amber 示範資料 (settlement
    is a demo page); no extra wiring needed.

## Tests

- `tests/integration/test_settlement.py` (service): seed a known scenario
  (1 farm, 1 customer, 1 contract, per-slot generation + consumption), call
  `compute_settlement`, assert: green_transfer_cost == Σ slot green_cost ==
  seller.sales_revenue; wheeling == green_mwh×1000×fee; customer_payable ==
  transfer + wheeling; retailer_margin == gross_profit − wheeling;
  carbon == green_mwh × factor; grey reference sums correctly.
- `tests/integration/test_settlement_api.py` (endpoint): default + override
  (transfer/wheeling) return 200 with expected totals; unknown customer → 404.
- Edge: a period with no allocations → zeros, no divide-by-zero.

## Gate

Full local gate before commit/merge/push: `ruff check app tests` · `black --check
app tests` · **`mypy app`** · `pytest` · `node --check web/app.js web/api.js`.
SSH remote for push. Live smoke on Render after deploy.

## Out of scope / future

Per-slot differentiated transfer pricing (TOU green PPA), multi-customer batch
settlement run, PDF/CSV export, bill persistence & numbering.
