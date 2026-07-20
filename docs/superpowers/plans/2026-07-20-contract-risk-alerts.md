# 合約風險告警 Implementation Plan

> REQUIRED SUB-SKILL: superpowers:executing-plans / subagent-driven-development.

**Goal:** Severity-ranked contract risk alerts (expiry / under-delivery / over-commitment / status-mismatch) via a service, endpoint, and dedicated SPA page.

**Architecture:** `risk_service.compute_contract_risks` projects over `Contract` (+ codes) and reuses `matching_service.compute_outcome(db, period)` for under-delivery. New endpoint + SPA page.

## Global Constraints

- Full gate before commit: `ruff` · `black` · **`mypy app`** · `pytest` · `node --check web/app.js web/api.js`.
- 3 severities `high`/`medium`/`low`; sort high→low then category.
- Reference date is a service param (endpoint passes `date.today()`); tests pass a fixed date.
- No data-model change. SSH push. Per-task commits.

---

### Task 1: Schema + risk service (TDD)

**Files:** Create `app/schemas/risk.py`, `app/services/risk_service.py`; Test `tests/integration/test_risk.py`.

- [ ] **Step 1: Failing tests** — `tests/integration/test_risk.py`. Fixed `reference_date=date(2026,7,20)`. Cases:
  - expiry: active contract `end_date=2026-09-15` → an `expiry` alert, severity `medium`.
  - status_mismatch: active contract `end_date=2026-03-01` → a `status_mismatch` alert (and NOT expiry).
  - over_commitment: two active contracts same farm Σ% = 130 → `over_commitment` `high`.
  - under_delivery: two contracts same farm (prio 1 @ 80%, prio 2 @ 80%), gen < demand → the priority-2 contract squeezed → an `under_delivery` alert.
  - counts consistent with alerts; `_SEVERITY_RANK` ordering (alerts[0].severity == "high" when a high exists).

```python
from __future__ import annotations
from datetime import date
import pytest
from app.models import ConsumptionData, Contract, Customer, GenerationData, WindFarm
from app.models.enums import ContractStatus, TimeSlot
from app.services.risk_service import compute_contract_risks

REF = date(2026, 7, 20)

def _farm(db, code="WF-A", cap=100.0):
    f = WindFarm(code=code, name=code, installed_capacity_mw=cap, feed_in_price_per_kwh=4.0)
    db.add(f); db.flush(); return f

def _cust(db, code="CU-A", target=50.0):
    c = Customer(code=code, company_name=code, re_target_percent=target)
    db.add(c); db.flush(); return c

def _contract(db, f, c, num, *, pct=None, energy=None, prio=1, status=ContractStatus.ACTIVE, start=date(2025,1,1), end=date(2032,12,31)):
    ct = Contract(contract_number=num, wind_farm_id=f.id, customer_id=c.id, start_date=start, end_date=end,
                  contracted_percentage=pct, contracted_energy_mwh=energy, price_per_kwh=5.0, priority=prio, status=status)
    db.add(ct); db.commit(); return ct

def test_expiry_medium(db):
    f, c = _farm(db), _cust(db)
    _contract(db, f, c, "X1", pct=50, end=date(2026, 9, 15))
    rep = compute_contract_risks(db, "2024-01", reference_date=REF, horizon_months=6)
    ex = [a for a in rep.alerts if a.category == "expiry"]
    assert ex and ex[0].severity == "medium" and ex[0].contract_number == "X1"

def test_status_mismatch_not_expiry(db):
    f, c = _farm(db), _cust(db)
    _contract(db, f, c, "X2", pct=50, end=date(2026, 3, 1))  # past, still active
    rep = compute_contract_risks(db, "2024-01", reference_date=REF, horizon_months=6)
    cats = {a.category for a in rep.alerts}
    assert "status_mismatch" in cats and "expiry" not in cats

def test_over_commitment_high(db):
    f, c = _farm(db), _cust(db)
    _contract(db, f, c, "X3", pct=70, prio=1)
    _contract(db, f, c, "X4", pct=60, prio=2)
    rep = compute_contract_risks(db, "2024-01", reference_date=REF, horizon_months=6)
    oc = [a for a in rep.alerts if a.category == "over_commitment"]
    assert oc and oc[0].severity == "high" and oc[0].wind_farm_code == "WF-A"

def test_under_delivery(db):
    f, c = _farm(db), _cust(db)
    # generation only 100 MWh in Jan; two 80% contracts compete → prio 2 squeezed
    db.add(GenerationData(wind_farm_id=f.id, period_start=date(2024,1,1), period_end=date(2024,1,31), generated_energy_mwh=100.0))
    db.add(ConsumptionData(customer_id=c.id, period_start=date(2024,1,1), period_end=date(2024,1,31), consumed_energy_mwh=500.0))
    _contract(db, f, c, "X5", pct=80, prio=1)
    _contract(db, f, c, "X6", pct=80, prio=2)
    rep = compute_contract_risks(db, "2024-01", reference_date=REF, horizon_months=6)
    ud = [a for a in rep.alerts if a.category == "under_delivery"]
    assert any(a.contract_number == "X6" for a in ud)

def test_no_risk_empty(db):
    f, c = _farm(db), _cust(db)
    _contract(db, f, c, "OK", pct=50, end=date(2032,12,31))
    rep = compute_contract_risks(db, "2099-01", reference_date=REF, horizon_months=6)
    assert rep.counts.total == len(rep.alerts)
```

- [ ] **Step 2:** Run → FAIL (import error).

- [ ] **Step 3:** `app/schemas/risk.py`:

```python
"""Contract risk alert schema."""

from __future__ import annotations

from pydantic import BaseModel


class RiskAlert(BaseModel):
    severity: str
    category: str
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
    reference_date: str
    horizon_months: int
    counts: RiskCounts
    alerts: list[RiskAlert]
```

- [ ] **Step 4:** `app/services/risk_service.py` — see spec; full logic:

```python
"""Contract risk alerts — projection over contracts + the matching outcome."""

from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Contract, Customer, WindFarm
from app.models.enums import ContractStatus
from app.schemas.risk import RiskAlert, RiskCounts, RiskReport
from app.services.matching_service import compute_outcome

_SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2}


def _add_months(d: date, months: int) -> date:
    m = d.month - 1 + months
    y = d.year + m // 12
    m = m % 12 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def compute_contract_risks(
    db: Session, period: str, *, reference_date: date, horizon_months: int
) -> RiskReport:
    contracts = list(db.execute(select(Contract)).scalars())
    farms = {f.id: f for f in db.execute(select(WindFarm)).scalars()}
    custs = {c.id: c for c in db.execute(select(Customer)).scalars()}
    horizon_end = _add_months(reference_date, horizon_months)

    def fcode(c: Contract) -> str | None:
        f = farms.get(c.wind_farm_id)
        return f.code if f else None

    def ccode(c: Contract) -> str | None:
        cu = custs.get(c.customer_id)
        return cu.code if cu else None

    alerts: list[RiskAlert] = []

    for c in contracts:
        # Rule 1: expiry
        if c.status == ContractStatus.ACTIVE and reference_date <= c.end_date <= horizon_end:
            days = (c.end_date - reference_date).days
            sev = "high" if days <= 31 else ("medium" if days <= 92 else "low")
            alerts.append(
                RiskAlert(
                    severity=sev, category="expiry", contract_number=c.contract_number,
                    wind_farm_code=fcode(c), customer_code=ccode(c),
                    title="合約即將到期",
                    detail=f"{c.contract_number} 於 {c.end_date.isoformat()} 到期(約 {days} 天後)。",
                    suggested_action="評估提前洽談續約或尋找替代綠電來源。",
                )
            )
        # Rule 4: status mismatch
        if c.end_date < reference_date and c.status == ContractStatus.ACTIVE:
            alerts.append(
                RiskAlert(
                    severity="medium", category="status_mismatch", contract_number=c.contract_number,
                    wind_farm_code=fcode(c), customer_code=ccode(c),
                    title="狀態不一致:已過期仍為有效",
                    detail=f"{c.contract_number} 已於 {c.end_date.isoformat()} 過期,狀態仍為 active。",
                    suggested_action="更新合約狀態為 expired,或辦理續約。",
                )
            )
        elif c.start_date <= reference_date and c.status == ContractStatus.PENDING:
            alerts.append(
                RiskAlert(
                    severity="medium", category="status_mismatch", contract_number=c.contract_number,
                    wind_farm_code=fcode(c), customer_code=ccode(c),
                    title="狀態不一致:已到生效日仍待生效",
                    detail=f"{c.contract_number} 生效日 {c.start_date.isoformat()} 已到,狀態仍為 pending。",
                    suggested_action="確認是否已生效並更新狀態為 active。",
                )
            )

    # Rule 3: over-commitment (per farm Σ active %)
    farm_pct: dict[int, float] = defaultdict(float)
    for c in contracts:
        if c.status == ContractStatus.ACTIVE and c.contracted_percentage:
            farm_pct[c.wind_farm_id] += c.contracted_percentage
    for fid, total in farm_pct.items():
        if total > 100.0:
            f = farms.get(fid)
            sev = "high" if total > 120.0 else "medium"
            alerts.append(
                RiskAlert(
                    severity=sev, category="over_commitment", contract_number=None,
                    wind_farm_code=(f.code if f else None), customer_code=None,
                    title="風場超額承諾",
                    detail=f"風場 {f.code if f else fid} 有效合約承諾比例合計 {round(total, 1)}%,超過 100%。",
                    suggested_action="檢視合約組合,避免超賣導致供電不足。",
                )
            )

    # Rule 2: under-delivery (period matching)
    outcome = compute_outcome(db, period)
    delivered = {a.contract_id: a.allocated_mwh for a in outcome.allocations}
    farm_gen = {f.farm_id: f.generated_mwh for f in outcome.farm_summaries}
    for c in contracts:
        if c.status != ContractStatus.ACTIVE:
            continue
        caps: list[float] = []
        if c.contracted_energy_mwh:
            caps.append(c.contracted_energy_mwh)
        if c.contracted_percentage:
            caps.append(c.contracted_percentage / 100.0 * farm_gen.get(c.wind_farm_id, 0.0))
        if not caps:
            continue
        expected = min(caps)
        if expected <= 0:
            continue
        dv = delivered.get(c.id, 0.0)
        short_pct = (expected - dv) / expected * 100.0
        if short_pct > 5.0:
            sev = "high" if short_pct >= 50 else ("medium" if short_pct >= 20 else "low")
            alerts.append(
                RiskAlert(
                    severity=sev, category="under_delivery", contract_number=c.contract_number,
                    wind_farm_code=fcode(c), customer_code=ccode(c),
                    title="供電不足",
                    detail=f"{c.contract_number} 於 {period} 實送 {round(dv, 1)} MWh,低於預期上限 {round(expected, 1)} MWh(缺口 {round(short_pct, 1)}%)。",
                    suggested_action="檢視優先序或增加供給,以滿足合約電量。",
                )
            )

    alerts.sort(key=lambda a: (_SEVERITY_RANK[a.severity], a.category))
    counts = RiskCounts(
        high=sum(1 for a in alerts if a.severity == "high"),
        medium=sum(1 for a in alerts if a.severity == "medium"),
        low=sum(1 for a in alerts if a.severity == "low"),
        total=len(alerts),
    )
    return RiskReport(
        period=period,
        reference_date=reference_date.isoformat(),
        horizon_months=horizon_months,
        counts=counts,
        alerts=alerts,
    )
```

- [ ] **Step 5:** Run tests → PASS. Gate (ruff/black/mypy). Commit `feat(risk): contract risk service + schema`.

---

### Task 2: Endpoint + API test

**Files:** Modify `app/api/v1/analytics.py`; Test `tests/integration/test_risk_api.py`.

- [ ] **Step 1: Failing API test** — seed a near-expiry active contract; GET `/api/v1/analytics/contract-risks?period=2024-01` → 200, `counts.total == len(alerts)`, an `expiry` alert present. (reference_date is server today; seed a contract ending ~2 months after `date.today()` computed in the test to stay deterministic.)

- [ ] **Step 2:** Run → FAIL (404).

- [ ] **Step 3:** In `app/api/v1/analytics.py`:

```python
from datetime import date
from app.schemas.risk import RiskReport
from app.services import risk_service as risk_svc
```

```python
@router.get("/contract-risks", response_model=RiskReport)
def contract_risks(
    period: str = _period,
    horizon_months: int = Query(6, ge=1, le=60),
    db: Session = Depends(get_db),
) -> RiskReport:
    """Severity-ranked contract risk alerts."""
    return risk_svc.compute_contract_risks(
        db, period, reference_date=date.today(), horizon_months=horizon_months
    )
```

- [ ] **Step 4:** Run → PASS. Gate. Commit `feat(risk): contract-risks endpoint`.

---

### Task 3: SPA page

**Files:** Modify `web/api.js`, `web/index.html`, `web/styles.css`, `web/app.js`.

- [ ] **Step 1:** `web/api.js` add:

```javascript
    contractRisks: function (period, horizonMonths) {
      return get("/analytics/contract-risks", { period: period, horizon_months: horizonMonths });
    },
```

- [ ] **Step 2:** `web/styles.css` add high-severity red pill:

```css
.pill.bad{background:var(--bad-soft);color:var(--bad)}
```

- [ ] **Step 3:** `web/index.html` — add nav item after 轉供結算 (監控/結算 group):

```html
        <a data-route="risks"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M12 3l9 16H3z"/><path d="M12 10v4M12 17h.01"/></svg>風險告警</a>
```

- [ ] **Step 4:** `web/app.js` — router `views`: add `risks: renderRisks,`. Then add:

```javascript
  // ---------- 合約風險告警 ----------
  var SEV = { high: ["高", "bad"], medium: ["中", "warnp"], low: ["低", "ok"] };
  var RISK_CAT = { expiry: "即將到期", under_delivery: "供電不足", over_commitment: "超額承諾", status_mismatch: "狀態不一致" };
  function sevPill(s) { var x = SEV[s] || [s, "warnp"]; return '<span class="pill ' + x[1] + '"><span class="dot"></span>' + x[0] + "</span>"; }

  function renderRisks() {
    crumb.textContent = "風險告警";
    view.innerHTML =
      '<div class="pagehead"><div class="title"><span class="bar"></span><h1>合約風險告警</h1></div>' +
      '<div class="meta"><span>掃描所有合約:即將到期、供電不足、風場超額承諾、狀態不一致,依嚴重度排序。</span></div></div>' +
      '<form class="formcard" id="rkForm"><div class="formgrid">' +
      '<div class="field"><label>供電不足評估期間 (YYYY-MM)</label><input id="r-period" class="num" value="2024-01"></div>' +
      '<div class="field"><label>到期預警月數</label><input id="r-horizon" class="num" type="number" min="1" max="60" value="6"></div>' +
      '</div><div class="formactions"><button class="btn primary" type="submit">' +
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 3l9 16H3z"/><path d="M12 10v4M12 17h.01"/></svg>掃描風險</button></div></form>' +
      '<div id="rk-body"><div class="placeholder">載入中…</div></div>';
    function run() {
      var period = document.getElementById("r-period").value.trim();
      var hz = parseInt(document.getElementById("r-horizon").value, 10) || 6;
      var body = document.getElementById("rk-body");
      body.innerHTML = '<div class="placeholder">掃描中…</div>';
      api.contractRisks(period, hz).then(function (r) { renderRiskReport(body, r); })
        .catch(function (err) { body.innerHTML = errbox("掃描風險", err); });
    }
    document.getElementById("rkForm").addEventListener("submit", function (e) { e.preventDefault(); run(); });
    run();
  }

  function renderRiskReport(body, r) {
    var k = r.counts;
    var html = '<div class="kpis">' +
      kpi("高風險", '<span class="neg">' + k.high + "</span>", "需立即處理") +
      kpi("中風險", '<span class="prem">' + k.medium + "</span>", "需關注") +
      kpi("低風險", k.low, "提醒") +
      kpi("告警總數", k.total + "<small>則</small>", "期間 " + esc(r.period) + " · 基準日 " + esc(r.reference_date), "hl") +
      "</div>";
    html += '<section class="card"><div class="hd"><h3>告警清單</h3><span class="aside">依嚴重度排序 · 到期預警 ' + r.horizon_months + " 個月</span></div><div class=\"tablewrap\"><table>" +
      "<thead><tr><th>嚴重度</th><th>類型</th><th>影響對象</th><th>說明</th><th>建議動作</th></tr></thead><tbody>";
    if (!r.alerts.length) {
      html += '<tr><td class="empty" colspan="5">目前無風險告警 ✓</td></tr>';
    } else {
      r.alerts.forEach(function (a) {
        var who = [a.contract_number, a.wind_farm_code, a.customer_code].filter(Boolean).map(esc).join(" · ") || "–";
        html += "<tr><td>" + sevPill(a.severity) + "</td><td>" + (RISK_CAT[a.category] || esc(a.category)) +
          "</td><td style=\"text-align:left\">" + who + "</td><td style=\"text-align:left\">" + esc(a.detail) +
          "</td><td style=\"text-align:left\">" + esc(a.suggested_action) + "</td></tr>";
      });
    }
    html += "</tbody></table></div></section>";
    html += '<div class="foot-note">' + iconInfo() + "到期/狀態以今日為基準;供電不足以選定期間的媒合結果比對合約預期上限。示範資料。</div>";
    body.innerHTML = html;
  }
```

- [ ] **Step 5:** `node --check`. Local smoke: run uvicorn, screenshot `/app/#/risks`. Commit `feat(risk): risk alerts SPA page`.

---

### Task 4: Demo data (trigger each risk)

**Files:** Modify `data/sample/contracts.csv`.

- [ ] Edit rows: `PPA-TPC-005` end_date → `2026-08-10`; `PPA-TPC-006` end_date → `2026-10-15` and `contracted_percentage` 15 → 55; `PPA-TPC-008` end_date → `2026-03-31` (status stays active).
- [ ] Re-seed the LOCAL db (`.venv/bin/python -m scripts.seed --reset --source sample`) and screenshot the risks page showing alerts of each severity.
- [ ] Commit `chore(risk): demo contracts trigger each risk category`.

---

### Final

- [ ] Full gate. Merge `feat/contract-risk-alerts` → main (no-ff), push SSH.
- [ ] After Render deploy, live smoke `GET /api/v1/analytics/contract-risks?period=2024-01`: `counts.total == len(alerts)`.
- [ ] Tell the user to re-seed live once via Render Shell (`python -m scripts.seed --reset --source sample`) so the live demo shows the triggered alerts.
- [ ] Optionally add a risks screenshot to README.
