# RE 目標建議 (RE Target Recommendations) Design

**Date:** 2026-07-20
**Status:** Approved (design)

## Goal

For a customer + period that is **under** its RE target, recommend which farms
(with surplus/unallocated green) to contract with to close the gap, **cheapest
first**. Pure analysis layer — no model/migration, no matching change.

## Data source (DRY)

- Customer gap ← `analytics_service.customer_analytics(db, period)` → the row for
  `customer_id`: `target_energy_mwh`, `allocated_mwh` (current green),
  `gap_to_target_mwh`, `re_target_percent`, `code`, `company_name`.
- Farm surplus ← `analytics_service.wind_farm_analytics(db, period)` →
  `unallocated_mwh` per farm.
- Farm feed-in price ← `WindFarm.feed_in_price_per_kwh` (fallback
  `settings.default_feed_in_price_per_kwh`). Indicative procurement cost.
- Existing contracts ← the customer's active contracts' `wind_farm_id` set →
  label each recommendation 擴約 (expand) vs 新簽 (new).

## Algorithm (cheapest-first greedy)

1. `gap = row.gap_to_target_mwh`. If `gap <= 1e-9` → already met / no target:
   return `recommendations=[]`, `fully_closable=True`, `residual_gap_mwh=0`.
2. Candidates = farms with `unallocated_mwh > 1e-9`, sorted by
   `(feed_in_price asc, -unallocated_mwh)` (cheapest first; tie → most surplus).
3. For each candidate while `remaining > 1e-9`:
   `recommended = min(surplus, remaining)`;
   `est_cost = recommended * 1000 * price`;
   `gap_covered_percent = recommended / gap * 100`; `remaining -= recommended`.
4. `residual_gap_mwh = max(0, remaining)`; `fully_closable = residual <= 1e-9`.
5. Unknown `customer_id` (not in the analytics list) → `NotFoundError` (404).

## Schema (`app/schemas/recommendation.py`)

```python
class FarmRecommendation(BaseModel):
    wind_farm_id: int
    code: str
    name: str
    available_surplus_mwh: float
    recommended_mwh: float
    gap_covered_percent: float
    feed_in_price_per_kwh: float
    est_cost: float
    has_existing_contract: bool

class ReTargetAdvice(BaseModel):
    customer_id: int
    customer_code: str
    company_name: str
    period: str
    re_target_percent: float
    target_energy_mwh: float
    current_green_mwh: float
    gap_mwh: float
    fully_closable: bool
    residual_gap_mwh: float
    total_recommended_mwh: float
    total_est_cost: float
    recommendations: list[FarmRecommendation]
```

## Service (`app/services/recommendation_service.py`)

`compute_re_recommendations(db, customer_id, period) -> ReTargetAdvice` — per the
algorithm above; reuses `analytics_service.customer_analytics` /
`wind_farm_analytics`; loads `WindFarm` feed-in prices and the customer's active
contract farm-id set.

## Endpoint (`app/api/v1/analytics.py`)

```
GET /api/v1/analytics/re-recommendations?customer_id=<int, ge=1>&period=<YYYY-MM>
→ ReTargetAdvice
```

## SPA (`web/`)

- `web/api.js`: `reRecommendations(customerId, period)`.
- `web/index.html`: nav under 媒合評估, after 投資效益: `<a data-route="recommend">…RE 建議</a>`.
- `web/app.js`: router `recommend: renderRecommend`; `renderRecommend` (customer +
  period form) → `renderRecommendResult`:
  - KPI: 目標電量 · 目前綠電 · 缺口(MWh) · 可否補足(綠 pill / 紅 pill).
  - If `gap_mwh <= 0`: a success card "✓ 已達標,無需補足".
  - Else table: 風場 · 可補電量(recommended) · 佔缺口% · 躉售價 · 估計成本 · 新簽/擴約.
  - Summary line: 需簽約 total_recommended MWh · 估計總成本 · 是否完全補足(residual if not).
  - Footnote: cheapest-first note; feed-in price is indicative. Data badge 示範資料.

## Tests

- `tests/integration/test_recommendation.py` (service): a customer with a known
  gap + two surplus farms at different prices → assert cheapest-first order,
  `Σ recommended == min(gap, Σ surplus)`, `fully_closable`/`residual` correct,
  `has_existing_contract` flag. A met customer → empty recommendations,
  `fully_closable=True`.
- `tests/integration/test_recommendation_api.py`: 200, totals consistent; unknown
  customer 404.

## Gate

`ruff` · `black` · **`mypy app`** · `pytest` · `node --check`. SSH push, live smoke.

## Out of scope

Multi-period planning, contract-price negotiation modelling, an optimiser that
also reshuffles existing allocations (this only proposes *new/expanded* supply
for the residual gap).
