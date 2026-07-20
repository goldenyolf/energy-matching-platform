# P5 — 轉供結算帳單 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** A two-sided, per-time-slot transfer settlement bill (轉供結算單) per customer/period, derived from the existing `compute_customer_optimization`, plus a Taipower wheeling fee and carbon-reduction, rendered as a formal invoice-style SPA page.

**Architecture:** New `settlement_service.compute_settlement` wraps `compute_customer_optimization` (no new matching) and projects it into a `SettlementResult`. New GET endpoint under `/analytics`. New SPA page reusing the evaluate-form pattern, rendering a bill.

**Tech Stack:** FastAPI · SQLAlchemy 2 · Pydantic v2 · dependency-free static SPA (vanilla JS). Python 3.12, `.venv`.

## Global Constraints

- Reply zh-TW; code comments match surrounding style.
- Full local gate before commit: `ruff check app tests` · `black --check app tests` · **`mypy app`** · `pytest` · `node --check web/app.js web/api.js`.
- Grey (灰電) is **reference only**, never part of `customer_payable`.
- DRY: do NOT reimplement matching; consume `CustomerOptimizationResult`.
- `_KWH = 1000.0`. Money rounded to 2 dp, MWh to 3 dp, percents to 4 dp, carbon to 2 dp in the result.
- Config defaults: `wheeling_fee_per_kwh = 0.1`, `grid_emission_factor_kg_per_kwh = 0.494` (illustrative).
- Push via SSH remote; per-task commits allowed; live smoke after Render deploy.

---

### Task 1: Config knobs + settlement schema

**Files:**
- Modify: `app/core/config.py` (after investment knobs)
- Create: `app/schemas/settlement.py`
- Test: `tests/unit/test_config_settlement.py`

**Interfaces:**
- Produces: `settings.wheeling_fee_per_kwh`, `settings.grid_emission_factor_kg_per_kwh`; schemas `SettlementSlotRow`, `SettlementParty`, `SettlementTotals`, `SettlementResult`.

- [ ] **Step 1: Failing config test** — `tests/unit/test_config_settlement.py`

```python
from app.core.config import Settings


def test_settlement_defaults():
    s = Settings()
    assert s.wheeling_fee_per_kwh == 0.1
    assert s.grid_emission_factor_kg_per_kwh == 0.494
```

- [ ] **Step 2:** Run `.venv/bin/python -m pytest tests/unit/test_config_settlement.py -q` → FAIL (AttributeError).

- [ ] **Step 3:** Add to `app/core/config.py` after the investment block:

```python
    # Transfer settlement (P5) — illustrative demo defaults
    wheeling_fee_per_kwh: float = 0.1  # NTD/kWh Taipower 轉供/輸配 service fee
    grid_emission_factor_kg_per_kwh: float = 0.494  # Taiwan 2023 grid factor
```

- [ ] **Step 4:** Rerun → PASS.

- [ ] **Step 5:** Create `app/schemas/settlement.py`:

```python
"""Transfer settlement bill (轉供結算單) response schema."""

from __future__ import annotations

from pydantic import BaseModel


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
    farms: list[SettlementParty]
    slots: list[SettlementSlotRow]
    totals: SettlementTotals
```

- [ ] **Step 6:** `.venv/bin/ruff check app tests && .venv/bin/black --check app tests && .venv/bin/mypy app` → clean. Commit `feat(p5): settlement config knobs + schema`.

---

### Task 2: Settlement service (core math, TDD)

**Files:**
- Create: `app/services/settlement_service.py`
- Test: `tests/integration/test_settlement.py`

**Interfaces:**
- Consumes: `compute_customer_optimization(db, customer_id, period, CustomerOptimizeOptions)` → `CustomerOptimizationResult`; `settings`.
- Produces: `compute_settlement(db, customer_id, period, opts: SettlementOptions) -> SettlementResult`; dataclass `SettlementOptions(transfer_price_per_kwh: float | None, wheeling_fee_per_kwh: float | None)`.

- [ ] **Step 1: Failing test** — `tests/integration/test_settlement.py`. Seed 1 farm (feed-in 4.0, capacity), 1 customer (re_target 50), 1 contract (price 5.0, 100%), per-slot generation + consumption so there is green in ≥1 slot. Then:

```python
from __future__ import annotations

from app.ingestion import csv_importer
from app.models import Customer
from app.services.settlement_service import SettlementOptions, compute_settlement


def _seed(db):
    csv_importer.import_wind_farms(db, [{"code": "WF-A", "name": "海能", "installed_capacity_mw": "100", "status": "operational", "feed_in_price_per_kwh": "4.0"}])
    csv_importer.import_customers(db, [{"code": "CU-A", "company_name": "Alpha", "annual_consumption_mwh": "2400", "re_target_percent": "50"}])
    csv_importer.import_contracts(db, [{"contract_number": "PPA-A", "wind_farm_code": "WF-A", "customer_code": "CU-A", "start_date": "2024-01-01", "end_date": "2030-12-31", "contracted_percentage": "100", "price_per_kwh": "5.0", "priority": "1", "status": "active"}])
    csv_importer.import_generation(db, [
        {"wind_farm_code": "WF-A", "period_start": "2024-01-01", "period_end": "2024-01-31", "generated_energy_mwh": "300", "data_source": "t", "time_slot": "peak"},
        {"wind_farm_code": "WF-A", "period_start": "2024-01-01", "period_end": "2024-01-31", "generated_energy_mwh": "300", "data_source": "t", "time_slot": "off_peak"},
    ])
    csv_importer.import_consumption(db, [
        {"customer_code": "CU-A", "period_start": "2024-01-01", "period_end": "2024-01-31", "consumed_energy_mwh": "500", "data_source": "t", "time_slot": "peak"},
        {"customer_code": "CU-A", "period_start": "2024-01-01", "period_end": "2024-01-31", "consumed_energy_mwh": "500", "data_source": "t", "time_slot": "off_peak"},
    ])
    return db.query(Customer).filter_by(code="CU-A").one().id


def test_settlement_totals_consistent(db):
    cid = _seed(db)
    r = compute_settlement(db, cid, "2024-01", SettlementOptions(transfer_price_per_kwh=None, wheeling_fee_per_kwh=0.1))
    t = r.totals
    # green transfer cost == sum of per-slot green cost
    assert t.green_transfer_cost == round(sum(s.green_cost for s in r.slots), 2)
    # wheeling == green kWh × fee
    assert t.wheeling_fee == round(t.green_mwh * 1000 * 0.1, 2)
    # customer payable == transfer + wheeling
    assert t.customer_payable == round(t.green_transfer_cost + t.wheeling_fee, 2)
    # margin == payable − farm_receivable − wheeling  (i.e. transfer − procurement − wheeling)
    assert t.retailer_margin == round(t.green_transfer_cost - t.farm_receivable - t.wheeling_fee, 2)
    # carbon == green_mwh × factor
    assert t.carbon_avoided_tco2e == round(t.green_mwh * 0.494, 2)
    assert r.transfer_price_per_kwh > 0
    assert r.farms and r.farms[0].wind_farm_code == "WF-A"


def test_settlement_override_wheeling(db):
    cid = _seed(db)
    r = compute_settlement(db, cid, "2024-01", SettlementOptions(transfer_price_per_kwh=6.0, wheeling_fee_per_kwh=0.2))
    assert r.wheeling_fee_per_kwh == 0.2
    assert r.transfer_price_per_kwh == 6.0
    assert r.totals.wheeling_fee == round(r.totals.green_mwh * 1000 * 0.2, 2)
```

- [ ] **Step 2:** Run → FAIL (import error).

- [ ] **Step 3:** Create `app/services/settlement_service.py`:

```python
"""Transfer settlement bill (轉供結算單) — projection of the matching result.

Reuses ``compute_customer_optimization`` (no new matching); adds a Taipower
wheeling fee and a carbon-reduction figure, and lays the result out per TOU slot
for a formal two-sided bill.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.config import settings
from app.schemas.settlement import (
    SettlementParty,
    SettlementResult,
    SettlementSlotRow,
    SettlementTotals,
)
from app.services.customer_optimization_service import (
    CustomerOptimizeOptions,
    compute_customer_optimization,
)

_KWH = 1000.0


@dataclass(frozen=True)
class SettlementOptions:
    transfer_price_per_kwh: float | None = None
    wheeling_fee_per_kwh: float | None = None


def compute_settlement(
    db: Session, customer_id: int, period: str, opts: SettlementOptions
) -> SettlementResult:
    wheeling = (
        settings.wheeling_fee_per_kwh
        if opts.wheeling_fee_per_kwh is None
        else opts.wheeling_fee_per_kwh
    )
    factor = settings.grid_emission_factor_kg_per_kwh

    co = compute_customer_optimization(
        db,
        customer_id,
        period,
        CustomerOptimizeOptions(
            min_sites_per_customer=settings.optimize_min_sites_per_customer,
            min_site_allocation_percent=settings.optimize_min_site_allocation_percent,
            re_target_percent=None,
            transfer_price_per_kwh=opts.transfer_price_per_kwh,
        ),
    )

    green_total = co.buyer.green_mwh
    # single transfer price: prefer the value the optimizer used; else derive
    price = co.transfer_price_used
    if price is None:
        price = (
            co.seller.sales_revenue / (green_total * _KWH) if green_total > 0 else 0.0
        )

    slots: list[SettlementSlotRow] = []
    grey_total = 0.0
    for s in co.slot_breakdown:
        green_mwh = s.allocated_mwh
        grey_mwh = max(0.0, s.consumption_mwh - s.allocated_mwh)
        grey_total += grey_mwh
        slots.append(
            SettlementSlotRow(
                slot=s.slot,
                green_mwh=round(green_mwh, 3),
                transfer_price_per_kwh=round(price, 4),
                green_cost=round(green_mwh * _KWH * price, 2),
                grey_mwh=round(grey_mwh, 3),
                grey_price_per_kwh=s.grey_price_per_kwh,
                grey_cost=round(grey_mwh * _KWH * s.grey_price_per_kwh, 2),
            )
        )

    green_transfer_cost = co.seller.sales_revenue
    wheeling_fee = green_total * _KWH * wheeling
    grey_cost = sum(row.grey_cost for row in slots)
    customer_payable = green_transfer_cost + wheeling_fee
    farm_receivable = co.seller.procurement_cost
    retailer_margin = green_transfer_cost - farm_receivable - wheeling_fee
    margin_pct = (
        retailer_margin / customer_payable * 100.0 if customer_payable > 0 else 0.0
    )
    carbon = green_total * factor  # green_kWh × kg/kWh ÷ 1000 = green_mwh × factor

    farms = [
        SettlementParty(
            wind_farm_code=a.wind_farm_code,
            wind_farm_name=a.wind_farm_name,
            allocated_mwh=round(a.allocated_mwh, 3),
            contract_number=a.contract_number,
        )
        for a in co.allocations
    ]

    return SettlementResult(
        period=co.period,
        season=co.season,
        solver_status=co.solver_status,
        customer_id=co.customer_id,
        customer_code=co.customer_code,
        company_name=co.company_name,
        transfer_price_per_kwh=round(price, 4),
        wheeling_fee_per_kwh=wheeling,
        grid_emission_factor_kg_per_kwh=factor,
        farms=farms,
        slots=slots,
        totals=SettlementTotals(
            green_mwh=round(green_total, 3),
            grey_mwh=round(grey_total, 3),
            green_transfer_cost=round(green_transfer_cost, 2),
            wheeling_fee=round(wheeling_fee, 2),
            grey_cost=round(grey_cost, 2),
            customer_payable=round(customer_payable, 2),
            farm_receivable=round(farm_receivable, 2),
            retailer_margin=round(retailer_margin, 2),
            retailer_margin_percent=round(margin_pct, 4),
            carbon_avoided_tco2e=round(carbon, 2),
        ),
    )
```

- [ ] **Step 4:** Run tests → PASS. If `green_transfer_cost` vs Σ slot rounding drifts by 0.01, assert with `abs(... ) <= 0.01` instead.
- [ ] **Step 5:** `ruff` · `black` · `mypy app` clean. Commit `feat(p5): settlement service`.

---

### Task 3: Endpoint + API tests

**Files:**
- Modify: `app/api/v1/analytics.py`
- Test: `tests/integration/test_settlement_api.py`

**Interfaces:**
- Consumes: `compute_settlement`, `SettlementOptions`, `SettlementResult`.
- Produces: `GET /analytics/settlement`.

- [ ] **Step 1: Failing API test** — reuse the `_seed` from Task 2 (copy locally). Assert 200 + `body["totals"]["customer_payable"] == transfer + wheeling`; override changes wheeling; unknown customer → 404.

- [ ] **Step 2:** Run → FAIL (404 route missing).

- [ ] **Step 3:** In `app/api/v1/analytics.py` add imports and route:

```python
from app.schemas.settlement import SettlementResult
from app.services import settlement_service as settle_svc
from app.services.settlement_service import SettlementOptions
```

```python
@router.get("/settlement", response_model=SettlementResult)
def settlement(
    customer_id: int = Query(..., ge=1),
    period: str = _period,
    transfer_price_per_kwh: float | None = Query(None, ge=0.0),
    wheeling_fee_per_kwh: float | None = Query(None, ge=0.0),
    db: Session = Depends(get_db),
) -> SettlementResult:
    """Two-sided per-slot 轉供結算單 for a customer/period."""
    return settle_svc.compute_settlement(
        db,
        customer_id,
        period,
        SettlementOptions(
            transfer_price_per_kwh=transfer_price_per_kwh,
            wheeling_fee_per_kwh=wheeling_fee_per_kwh,
        ),
    )
```

- [ ] **Step 4:** Run tests → PASS. `ruff`·`black`·`mypy app` clean. Commit `feat(p5): settlement endpoint`.

---

### Task 4: SPA page (form + formal bill)

**Files:**
- Modify: `web/api.js`, `web/index.html`, `web/app.js`

**Interfaces:**
- Consumes: `GET /analytics/settlement`.

- [ ] **Step 1:** `web/api.js` — add after `investment`:

```javascript
    settlement: function (customerId, period, transferPrice, wheelingFee) {
      return get("/analytics/settlement", {
        customer_id: customerId,
        period: period,
        transfer_price_per_kwh: transferPrice,
        wheeling_fee_per_kwh: wheelingFee,
      });
    },
```

- [ ] **Step 2:** `web/index.html` — replace the disabled 轉供結算 item:

```html
        <a data-route="settlement"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M6 3h9l3 3v15H6z"/><path d="M9 12h6M9 16h6"/></svg>轉供結算</a>
```

- [ ] **Step 3:** `web/app.js` router `views` map — add `settlement: renderSettlement,`.

- [ ] **Step 4:** `web/app.js` — add `renderSettlement` + `renderSettlementBill` (insert near `renderInvestment`). Form mirrors `renderEvaluate` (customer select + 期間 + optional 轉供價 + 輸配費). On submit → `api.settlement(...)` → `renderSettlementBill(root, r)`.

```javascript
  function renderSettlement() {
    crumb.textContent = "轉供結算";
    view.innerHTML =
      '<div class="pagehead"><div class="title"><span class="bar"></span><h1>轉供結算單</h1></div>' +
      '<div class="meta"><span>選用電戶與期間,產出雙方逐時段轉供結算單(綠電轉供費、台電輸配費、售電毛利、減碳量)。</span></div></div>' +
      '<form class="formcard" id="stForm"><div class="formgrid">' +
      '<div class="field"><label>用電戶<span class="req">*</span></label><select id="s-customer" required><option value="">載入中…</option></select></div>' +
      '<div class="field"><label>期間 (YYYY-MM)</label><input id="s-period" class="num" value="2024-01"></div>' +
      '<div class="field"><label>轉供價</label><input id="s-transfer" class="num" type="number" min="0" step="0.1" placeholder="依合約"><span class="hint">NTD/kWh · 可覆寫</span></div>' +
      '<div class="field"><label>台電輸配費</label><input id="s-wheel" class="num" type="number" min="0" step="0.01" placeholder="0.1"><span class="hint">NTD/kWh · 可覆寫</span></div>' +
      '</div><div class="formactions"><button class="btn primary" type="submit">' +
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M4 7h16M7 12h10M10 17h4"/></svg>產生結算單</button></div></form>' +
      '<div id="st-result"></div>';
    var sel = document.getElementById("s-customer");
    api.customers().then(function (list) {
      sel.innerHTML = list.map(function (c) {
        return '<option value="' + c.id + '">' + esc(c.code + " · " + c.company_name) + "</option>";
      }).join("");
    }).catch(function (err) {
      sel.innerHTML = '<option value="">無法載入用電戶</option>';
      document.getElementById("st-result").innerHTML = errbox("載入用電戶", err);
    });
    document.getElementById("stForm").addEventListener("submit", function (e) {
      e.preventDefault();
      var cid = parseInt(sel.value, 10); if (!cid) { sel.focus(); return; }
      var period = document.getElementById("s-period").value.trim();
      var tv = document.getElementById("s-transfer").value.trim();
      var wv = document.getElementById("s-wheel").value.trim();
      showModal("正在產生轉供結算單…");
      var root = document.getElementById("st-result");
      api.settlement(cid, period, tv === "" ? null : parseFloat(tv), wv === "" ? null : parseFloat(wv))
        .then(function (r) { renderSettlementBill(root, r); })
        .catch(function (err) { root.innerHTML = errbox("產生結算單", err); })
        .then(function () { setTimeout(hideModal, reduce ? 0 : 300); });
    });
  }

  var SLOT_LABEL = { peak: "尖峰", half_peak: "半尖峰", off_peak: "離峰" };
  function slotName(s) { return SLOT_LABEL[s] || s; }

  function renderSettlementBill(root, r) {
    var t = r.totals;
    var farms = (r.farms || []).map(function (f) { return esc(f.wind_farm_code); }).join(" · ") || "–";
    var seasonLabel = r.season === "summer" ? "夏月" : "非夏月";
    var html = '<section class="card">' +
      '<div class="hd"><h3>轉供結算單 · ' + esc(r.period) + "</h3><span class=\"aside\">" + seasonLabel + " · " + esc(r.solver_status) + "</span></div>" +
      '<div class="rows"><div class="row"><span class="lab">用電戶</span><span class="val">' + esc(r.company_name) + " (" + esc(r.customer_code) + ")</span></div>" +
      '<div class="row"><span class="lab">供電風場</span><span class="val">' + farms + "</span></div>" +
      '<div class="row"><span class="lab">轉供價 / 輸配費</span><span class="val num">' + price(r.transfer_price_per_kwh) + " / " + price(r.wheeling_fee_per_kwh) + '<span class="u">NTD/kWh</span></span></div></div>';
    html += '<div class="tablewrap"><table><thead><tr><th>時段</th><th>綠電量 (MWh)</th><th>轉供價</th><th>綠電金額</th><th>灰電量 (MWh)</th><th>灰電TOU價</th><th>灰電金額</th></tr></thead><tbody>';
    (r.slots || []).forEach(function (s) {
      html += "<tr><td>" + slotName(s.slot) + "</td><td class=\"num\">" + nfmt(s.green_mwh, 0) + "</td><td class=\"num\">" + price(s.transfer_price_per_kwh) +
        "</td><td class=\"num\">" + money(s.green_cost) + "</td><td class=\"num\">" + nfmt(s.grey_mwh, 0) + "</td><td class=\"num\">" + price(s.grey_price_per_kwh) + "</td><td class=\"num\">" + money(s.grey_cost) + "</td></tr>";
    });
    html += "</tbody></table></div>";
    html += '<div class="rows">' +
      erow("綠電轉供費", money(t.green_transfer_cost), "NTD") +
      erow("台電輸配費", "+" + money(t.wheeling_fee), "NTD") +
      erowTotal("客戶應付合計", money(t.customer_payable), "NTD", "pos") +
      erow("風場應收", money(t.farm_receivable), "NTD") +
      erow("售電業毛利", money(t.retailer_margin) + " (" + pct(t.retailer_margin_percent) + "%)", "NTD", t.retailer_margin >= 0 ? "pos" : "neg") +
      erow("灰電補足（參考）", money(t.grey_cost), "NTD", "prem") +
      '</div>';
    html += '<div class="slotnote">' + iconInfo() + "減碳量 <b>" + nfmt(t.carbon_avoided_tco2e, 0) + " tCO₂e</b>（綠電 " + nfmt(t.green_mwh, 0) + " MWh × " + price(r.grid_emission_factor_kg_per_kwh) + " kgCO₂e/kWh）。灰電補足為客戶剩餘用電成本，僅供參考、不計入應付。</div>";
    html += "</section>";
    root.innerHTML = html;
  }
```

- [ ] **Step 5:** `node --check web/app.js && node --check web/api.js` → OK.
- [ ] **Step 6:** Manual smoke: run uvicorn on the local DB, screenshot `/app/#/settlement` after submitting a customer; confirm the bill renders and the data badge shows 示範資料. Commit `feat(p5): settlement SPA page`.

---

### Final

- [ ] Run the FULL gate (`ruff`·`black`·`mypy app`·`pytest`·`node --check`).
- [ ] Merge `feat/p5-settlement` → main (no-ff), push via SSH.
- [ ] After Render deploy, live smoke `GET /api/v1/analytics/settlement?customer_id=1&period=2024-01`: assert `customer_payable == green_transfer_cost + wheeling_fee` and `Σ slot green_cost == green_transfer_cost`.
- [ ] Optionally add a settlement screenshot to README.
