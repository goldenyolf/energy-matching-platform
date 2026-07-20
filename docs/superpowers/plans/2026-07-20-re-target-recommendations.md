# RE 目標建議 Implementation Plan

> REQUIRED SUB-SKILL: superpowers:executing-plans.

**Goal:** Cheapest-first recommendations of surplus farms to close a customer's RE gap. Pure analysis layer (no model/migration).

## Global Constraints

- Full gate: `ruff` · `black` · **`mypy app`** · `pytest` · `node --check`. SSH push, per-task commits.
- DRY: reuse `analytics_service.customer_analytics` / `wind_farm_analytics`. No matching change.

---

### Task 1: Schema + recommendation service (TDD)

**Files:** create `app/schemas/recommendation.py`, `app/services/recommendation_service.py`; test `tests/integration/test_recommendation.py`.

- [ ] **Step 1: failing tests** — customer with a gap + two surplus farms (prices 3.0 and 5.0); assert cheapest (3.0) first, `Σ recommended == min(gap, Σ surplus)`, `fully_closable`/`residual`, `has_existing_contract`. Met customer → empty + `fully_closable`.

```python
from datetime import date
import pytest
from app.models import ConsumptionData, Contract, Customer, GenerationData, WindFarm
from app.models.enums import ContractStatus
from app.services.recommendation_service import compute_re_recommendations


def _seed_gap(db):
    # customer needs 50% of 1000 = 500 green; only farm A (contracted) delivers 200 → gap 300.
    a = WindFarm(code="FA", name="A", installed_capacity_mw=100, feed_in_price_per_kwh=4.0)
    cheap = WindFarm(code="CHEAP", name="Cheap", installed_capacity_mw=100, feed_in_price_per_kwh=3.0)
    exp = WindFarm(code="EXP", name="Exp", installed_capacity_mw=100, feed_in_price_per_kwh=5.0)
    cust = Customer(code="CU", company_name="X", re_target_percent=50.0)
    db.add_all([a, cheap, exp, cust]); db.flush()
    db.add(GenerationData(wind_farm_id=a.id, period_start=date(2024,1,1), period_end=date(2024,1,31), generated_energy_mwh=200.0))
    db.add(GenerationData(wind_farm_id=cheap.id, period_start=date(2024,1,1), period_end=date(2024,1,31), generated_energy_mwh=250.0))
    db.add(GenerationData(wind_farm_id=exp.id, period_start=date(2024,1,1), period_end=date(2024,1,31), generated_energy_mwh=250.0))
    db.add(ConsumptionData(customer_id=cust.id, period_start=date(2024,1,1), period_end=date(2024,1,31), consumed_energy_mwh=1000.0))
    # only farm A is contracted (100%), so cheap/exp are all surplus; A's 200 all goes to the customer
    db.add(Contract(contract_number="C-A", wind_farm_id=a.id, customer_id=cust.id, start_date=date(2024,1,1), end_date=date(2030,12,31), status=ContractStatus.ACTIVE, priority=1, contracted_percentage=100.0, price_per_kwh=5.0))
    db.commit()
    return cust


def test_cheapest_first_recommendations(db):
    cust = _seed_gap(db)
    r = compute_re_recommendations(db, cust.id, "2024-01")
    assert r.gap_mwh == pytest.approx(300.0, abs=1.0)
    assert r.recommendations[0].code == "CHEAP"  # cheapest first
    assert r.recommendations[0].feed_in_price_per_kwh == 3.0
    total = sum(x.recommended_mwh for x in r.recommendations)
    assert total == pytest.approx(min(r.gap_mwh, 500.0), abs=1.0)
    assert r.fully_closable is True  # 500 surplus > 300 gap
    assert r.residual_gap_mwh == pytest.approx(0.0, abs=1.0)
    # CHEAP (250) covers 250 of the 300 gap; EXP covers the remaining 50
    cheap = next(x for x in r.recommendations if x.code == "CHEAP")
    assert cheap.recommended_mwh == pytest.approx(250.0, abs=1.0)
    assert cheap.has_existing_contract is False


def test_met_customer_no_recommendations(db):
    cust = Customer(code="MET", company_name="M", re_target_percent=0.0)
    db.add(cust); db.commit()
    r = compute_re_recommendations(db, cust.id, "2024-01")
    assert r.recommendations == [] and r.fully_closable is True
```

- [ ] **Step 2:** run → FAIL. **Step 3:** `app/schemas/recommendation.py` (per spec). **Step 4:** `app/services/recommendation_service.py`:

```python
"""RE target recommendations: cheapest-first surplus farms to close a gap."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.models import Contract, WindFarm
from app.models.enums import ContractStatus
from app.schemas.recommendation import FarmRecommendation, ReTargetAdvice
from app.services import analytics_service as an

_KWH = 1000.0


def compute_re_recommendations(
    db: Session, customer_id: int, period: str
) -> ReTargetAdvice:
    row = next(
        (c for c in an.customer_analytics(db, period) if c.customer_id == customer_id),
        None,
    )
    if row is None:
        raise NotFoundError(f"customer {customer_id} not found")

    base = dict(
        customer_id=row.customer_id,
        customer_code=row.code,
        company_name=row.company_name,
        period=period,
        re_target_percent=row.re_target_percent,
        target_energy_mwh=round(row.target_energy_mwh, 3),
        current_green_mwh=round(row.allocated_mwh, 3),
    )
    gap = row.gap_to_target_mwh
    if gap <= 1e-9:
        return ReTargetAdvice(
            **base, gap_mwh=0.0, fully_closable=True, residual_gap_mwh=0.0,
            total_recommended_mwh=0.0, total_est_cost=0.0, recommendations=[],
        )

    default_price = settings.default_feed_in_price_per_kwh
    farms = {f.id: f for f in db.execute(select(WindFarm)).scalars()}
    existing = {
        c.wind_farm_id
        for c in db.execute(
            select(Contract).where(
                Contract.customer_id == customer_id,
                Contract.status == ContractStatus.ACTIVE,
            )
        ).scalars()
    }

    def price_of(fa) -> float:
        f = farms.get(fa.wind_farm_id)
        p = f.feed_in_price_per_kwh if f else None
        return p if p is not None else default_price

    candidates = [
        fa for fa in an.wind_farm_analytics(db, period) if fa.unallocated_mwh > 1e-9
    ]
    candidates.sort(key=lambda fa: (price_of(fa), -fa.unallocated_mwh))

    recos: list[FarmRecommendation] = []
    remaining = gap
    for fa in candidates:
        if remaining <= 1e-9:
            break
        take = min(fa.unallocated_mwh, remaining)
        p = price_of(fa)
        recos.append(
            FarmRecommendation(
                wind_farm_id=fa.wind_farm_id,
                code=fa.code,
                name=fa.name,
                available_surplus_mwh=round(fa.unallocated_mwh, 3),
                recommended_mwh=round(take, 3),
                gap_covered_percent=round(take / gap * 100.0, 4),
                feed_in_price_per_kwh=round(p, 4),
                est_cost=round(take * _KWH * p, 2),
                has_existing_contract=fa.wind_farm_id in existing,
            )
        )
        remaining -= take

    residual = max(0.0, remaining)
    return ReTargetAdvice(
        **base,
        gap_mwh=round(gap, 3),
        fully_closable=residual <= 1e-9,
        residual_gap_mwh=round(residual, 3),
        total_recommended_mwh=round(sum(x.recommended_mwh for x in recos), 3),
        total_est_cost=round(sum(x.est_cost for x in recos), 2),
        recommendations=recos,
    )
```

- [ ] **Step 5:** run → PASS. Gate. Commit `feat(reco): RE recommendation service + schema`.

---

### Task 2: Endpoint + API test

**Files:** modify `app/api/v1/analytics.py`; test `tests/integration/test_recommendation_api.py`.

- [ ] Failing API test (seed a gap, hit endpoint) → add:

```python
from app.schemas.recommendation import ReTargetAdvice
from app.services import recommendation_service as reco_svc
```
```python
@router.get("/re-recommendations", response_model=ReTargetAdvice)
def re_recommendations(
    customer_id: int = Query(..., ge=1),
    period: str = _period,
    db: Session = Depends(get_db),
) -> ReTargetAdvice:
    """Cheapest-first surplus-farm recommendations to close a customer's RE gap."""
    return reco_svc.compute_re_recommendations(db, customer_id, period)
```

Assert 200, `total_recommended_mwh <= gap_mwh + 1e-6`, cheapest-first; unknown customer 404. Gate. Commit `feat(reco): re-recommendations endpoint`.

---

### Task 3: SPA page

**Files:** modify `web/api.js`, `web/index.html`, `web/app.js`.

- [ ] `web/api.js`: `reRecommendations(customerId, period)` → `/analytics/re-recommendations`.
- [ ] `web/index.html`: nav under 媒合評估 after 投資效益: `<a data-route="recommend">…RE 建議</a>` (lightbulb/target icon).
- [ ] `web/app.js`: router `recommend: renderRecommend`; `renderRecommend` (customer+period form) → `renderRecommendResult`:
  - KPI: 目標電量 · 目前綠電 · 缺口(MWh) · 可否補足(metPill-style: 綠 pill 可補足 / 紅 pill 尚缺 residual).
  - `gap_mwh <= 0` → success card "✓ 已達標或無 RE 缺口,無需補足".
  - Else table: 風場(code+name) · 可補電量 · 佔缺口% · 躉售價 · 估計成本 · 類型(新簽/擴約 pill).
  - Summary + footnote (cheapest-first; 躉售價為指示性成本). Data badge 示範資料 by route.
- [ ] `node --check`. Local smoke: screenshot `/app/#/recommend` for an under-target customer (e.g. 台積電). Commit `feat(reco): RE 建議 SPA page`.

---

### Final

- [ ] Full gate. Merge `feat/re-recommendations` → main, push SSH.
- [ ] Live smoke `GET /analytics/re-recommendations?customer_id=1&period=2024-01`.
- [ ] Optionally README screenshot. (No re-seed needed — pure analysis over existing data.)
