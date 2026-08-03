# 合約詳情頁（商務視角）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 讓合約清單的每一列可以點進去，看到這紙合約在某一年的逐月履約、被哪個約束卡住，以及買方／賣方／售電業三方的帳。

**Architecture:** 新增一支唯讀 analytics 端點 `GET /analytics/contract-detail?contract_id&year`，後端跑 12 次既有的 `compute_outcome()`，把單一合約的月度分配、綁定約束與金額攤成一個 `ContractDetail`。前端新增一個 hash 路由 `#/contract?id=&year=` 渲染五個區塊。**媒合引擎一行不改。**

**Tech Stack:** FastAPI · SQLAlchemy 2.x · Pydantic v2 · pytest · 零依賴無 build 的靜態 SPA（ES5 風格 JS）

**Spec:** `docs/superpowers/specs/2026-07-31-contract-detail-design.md`

## Global Constraints

- **`app/matching/engine.py` 與 `app/matching/contract_terms.py` 唯讀，一行不改。**
- **不動 `data/sample/*.csv`。** take-or-pay 在示範資料上不會觸發，頁面照實顯示「未觸發」。
- **不新增資料表、不新增欄位、不需要 Alembic migration。** 本功能純粹是既有資料的投影。
- **null 不得變成 0。** 「未設上限」與「使用率 0%」是兩件事；`cap_mwh is None` 時 `utilization_percent` 必須也是 `None`。
- **不計算「履約健康度分數」。** 只呈現可查證的事實。
- 前端零依賴、無 build step：`var`、字串串接、`function` 宣告，禁止 `const`/`let`/箭頭函式/樣板字串（其餘檔案皆為此風格，`node --check` 不會擋但要一致）。
- 金額格式一律用既有 `money()`；電量用 `nfmt(v, 0|1)`；百分比用 `pct()`；單價用 `price()`。
- **閘門（每個 task 結束前必跑，與 CI 同一組指令）：**

  ```bash
  .venv/bin/ruff check app tests
  .venv/bin/black --check app tests
  .venv/bin/mypy app
  .venv/bin/pytest -q --cov=app --cov-report=term-missing --cov-fail-under=90
  node --check web/app.js && node --check web/api.js
  ```

  注意範圍是 `app tests` 而**不是** `.`——`alembic/` 底下有既有的排版差異，不在閘門內，也不要順手去改。
- **本計畫內的 Python 程式碼片段未經 black 排版，部分行超過 `line-length = 88`。** 貼進檔案後先跑一次 `.venv/bin/black <該檔案>`，再手動把 black 不會拆的長字串以隱式串接折行。**字串內容一個字元都不能改**——那些是引擎實際輸出的 `reason`，改了測試就是在對一個不存在的字串斷言。不得用 `# noqa`，不得改 `pyproject.toml`。
- **絕不 `git add -A`**，只加該 task 明確列出的路徑。
- Commit 訊息結尾固定加 `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`。
- 執行測試請用專案 venv：`.venv/bin/pytest`、`.venv/bin/ruff`、`.venv/bin/black`、`.venv/bin/mypy`。

## File Structure

| 檔案 | 責任 | Task |
|---|---|---|
| `app/services/contract_detail_service.py` | 新增。綁定約束分類、加購空間判定、12 個月履約序列、雙面帳金額 | 1–3 |
| `app/schemas/contract_detail.py` | 新增。`ContractMonth` / `ContractYearTotals` / `ContractDetail` | 2 |
| `app/api/v1/analytics.py` | 修改。加一支 `GET /contract-detail` | 4 |
| `web/api.js` | 修改。加 `api.contractDetail()` | 4 |
| `web/app.js` | 修改。路由 `contract`、`renderContractDetail()` 與五個區塊 | 5–7 |
| `web/styles.css` | 修改。新區塊樣式 | 5–7 |
| `tests/unit/test_contract_detail.py` | 新增。純函式與 service 單元測試 | 1–3 |
| `tests/integration/test_contract_detail_api.py` | 新增。端點與示範資料事實 | 4 |
| `CHANGELOG.md` | 修改。Unreleased 條目 | 8 |

---

## Task 1: 綁定約束分類與加購空間判定（純函式）

引擎把綁定約束寫成給人讀的字串（`allocated 1250.0 MWh (limited by wind farm supply, contract cap)`）。這個 task 把它變成可上色、可統計的代碼，並實作「有沒有加購空間」這個**必須有資料撐腰**的判定。兩者都是純函式，先獨立釘死再往上疊。

**Files:**
- Create: `app/services/contract_detail_service.py`
- Test: `tests/unit/test_contract_detail.py`

**Interfaces:**
- Consumes: 無
- Produces:
  - `classify_binding(reason: str) -> tuple[list[str], str]`
  - `has_headroom(binding_primary: str, farm_unallocated_mwh: float, customer_unmet_mwh: float) -> bool`
  - 模組常數 `EPS: float = 1e-9`

- [ ] **Step 1: 寫失敗的測試**

建立 `tests/unit/test_contract_detail.py`：

```python
"""合約詳情：綁定約束分類與加購空間判定。

引擎的 reason 是給人讀的字串,這裡把它變成可上色、可統計的代碼。
「有沒有加購空間」則是三個條件的合取——少一個,那句話就是假的。
"""

from __future__ import annotations

import pytest

from app.services.contract_detail_service import classify_binding, has_headroom


@pytest.mark.parametrize(
    ("reason", "expected"),
    [
        ("allocated 1250.0 MWh (limited by contract cap)", (["contract_cap"], "contract_cap")),
        ("allocated 900.0 MWh (limited by wind farm supply)", (["farm_supply"], "farm_supply")),
        ("allocated 800.0 MWh (limited by customer demand)", (["customer_demand"], "customer_demand")),
        ("allocated 5.0 MWh (limited by available supply)", ([], "none")),
        ("no allocation", ([], "none")),
    ],
)
def test_single_constraint_is_classified(reason, expected):
    assert classify_binding(reason) == expected


def test_multiple_constraints_keep_a_fixed_precedence():
    """同時綁定時只挑一個上色。案場供給用盡最硬——調高上限也拿不到更多電。"""
    binding, primary = classify_binding(
        "allocated 300.0 MWh (limited by wind farm supply, contract cap)"
    )
    assert binding == ["farm_supply", "contract_cap"]
    assert primary == "farm_supply"


def test_precedence_is_supply_then_demand_then_cap():
    _, primary = classify_binding(
        "allocated 0.0 MWh (limited by customer demand, contract cap)"
    )
    assert primary == "customer_demand"


@pytest.mark.parametrize(
    ("reason", "primary"),
    [
        ("no allocation: wind farm has no remaining generation", "farm_supply"),
        ("no allocation: customer consumption already fully covered", "customer_demand"),
        ("no allocation: contract cap is zero", "contract_cap"),
    ],
)
def test_zero_allocation_still_names_its_constraint(reason, primary):
    """零分配時引擎有講原因,退回 none 等於丟掉已知資訊。"""
    assert classify_binding(reason)[1] == primary


def test_headroom_needs_all_three_conditions():
    assert has_headroom("contract_cap", 500.0, 300.0) is True


@pytest.mark.parametrize(
    ("primary", "farm_left", "cust_unmet"),
    [
        ("farm_supply", 500.0, 300.0),   # 不是被上限卡住 → 調高上限無用
        ("contract_cap", 0.0, 300.0),    # 案場沒餘電 → 調高上限也拿不到
        ("contract_cap", 500.0, 0.0),    # 客戶已吃飽 → 多給也用不掉
    ],
)
def test_headroom_is_false_when_any_condition_fails(primary, farm_left, cust_unmet):
    assert has_headroom(primary, farm_left, cust_unmet) is False
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `.venv/bin/pytest tests/unit/test_contract_detail.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.contract_detail_service'`

- [ ] **Step 3: 寫最小實作**

建立 `app/services/contract_detail_service.py`：

```python
"""合約詳情（商務視角）：把 12 次月度媒合的結果攤成一紙合約的履約與帳。

引擎（``app/matching/engine.py``）不改,本模組唯讀使用它的輸出。
"""

from __future__ import annotations

EPS = 1e-9

# 引擎 reason 字串裡的用語 → 本模組的約束代碼。
# 前三個來自有分配的情況,後三個來自 ``no allocation: …``——零分配時引擎也講了
# 原因,對應回去比一律歸類成「無」更有資訊。
_BINDING_WORDS = {
    "wind farm supply": "farm_supply",
    "customer demand": "customer_demand",
    "contract cap": "contract_cap",
    "wind farm has no remaining generation": "farm_supply",
    "customer consumption already fully covered": "customer_demand",
    "contract cap is zero": "contract_cap",
}

# 同時綁定多個約束時只挑一個上色與統計。案場供給用盡是最硬的限制——
# 調高合約上限也拿不到更多電,所以它排最前面;合約上限最軟,排最後。
_PRECEDENCE = ("farm_supply", "customer_demand", "contract_cap")


def classify_binding(reason: str) -> tuple[list[str], str]:
    """把引擎的 reason 字串拆成約束代碼清單與單一主約束。

    回傳的清單依 ``_PRECEDENCE`` 排序（穩定,不受 reason 字序影響）;
    認不出任何約束時回 ``([], "none")``。
    """
    found = {code for word, code in _BINDING_WORDS.items() if word in reason}
    ordered = [c for c in _PRECEDENCE if c in found]
    return (ordered, ordered[0]) if ordered else ([], "none")


def has_headroom(
    binding_primary: str, farm_unallocated_mwh: float, customer_unmet_mwh: float
) -> bool:
    """這個月有沒有「加購空間」。

    三個條件缺一不可：被合約上限卡住、案場還有餘電、客戶還有沒被滿足的用電。
    少了後兩者任一,「調高上限就能多拿」這句話就是假的——所以不能只看綁定約束。
    """
    return (
        binding_primary == "contract_cap"
        and farm_unallocated_mwh > EPS
        and customer_unmet_mwh > EPS
    )
```

- [ ] **Step 4: 跑測試確認通過**

Run: `.venv/bin/pytest tests/unit/test_contract_detail.py -q`
Expected: PASS（14 passed）

- [ ] **Step 5: 跑閘門**

```bash
.venv/bin/ruff check app tests && .venv/bin/black --check app tests && .venv/bin/mypy app && .venv/bin/pytest -q
```
Expected: 全綠

- [ ] **Step 6: Commit**

```bash
git add app/services/contract_detail_service.py tests/unit/test_contract_detail.py
git commit -m "$(cat <<'EOF'
feat(contracts): classify the engine's binding constraint into a code

The engine already records which constraint bound each allocation, but only
as prose. Turn it into a code the UI can colour and count, with a fixed
precedence so a month bound by two constraints always reports the same one.
Supply wins over cap: if the farm ran out, raising the cap buys nothing.

Zero-allocation months keep their constraint too — the engine says why, and
collapsing that to "none" throws away what it told us.

has_headroom() is a conjunction of three conditions on purpose. A binding cap
alone does not mean the customer could buy more; the farm also needs spare
energy and the customer unmet demand. The sample data contains cases that
fail each condition, so the ungated version would print a false claim.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Schema 與履約序列

回傳 12 個月的履約資料與合約條款。**金額欄位這個 task 一律留 `None`，Task 3 才填**——不要為「金額是 None」寫測試，那是暫時狀態。

**Files:**
- Create: `app/schemas/contract_detail.py`
- Modify: `app/services/contract_detail_service.py`
- Test: `tests/unit/test_contract_detail.py`

**Interfaces:**
- Consumes: `classify_binding()`、`has_headroom()`、`EPS`（Task 1）
- Produces:
  - `app.schemas.contract_detail.ContractMonth` / `ContractYearTotals` / `ContractDetail`
  - `compute_contract_detail(db: Session, contract_id: int, year: int) -> ContractDetail`

- [ ] **Step 1: 寫 schema**

建立 `app/schemas/contract_detail.py`：

```python
"""合約詳情（商務視角）回應 schema。

一紙合約在某一年的逐月履約與雙面帳。金額欄位在合約未設售電價時全為 None——
用躉售價代入讓毛利變成 0 會是個看起來合理但不真實的數字。
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel


class ContractMonth(BaseModel):
    period: str                        # "2024-03"
    month: int                         # 1–12
    in_force: bool                     # False = 未生效／已到期／狀態非 active
    skip_reason: str | None            # 引擎原文,僅 in_force=False 時有值

    # 履約
    cap_mwh: float | None              # 本月合約上限（None = 未設上限,或該月未生效）
    cap_source: str                    # volume | percentage | both | none
    allocated_mwh: float
    utilization_percent: float | None  # allocated/cap；cap 為 None 或 0 時亦為 None
    min_offtake_mwh: float             # take-or-pay 門檻（0 = 無此條款／非量制／未生效）
    shortfall_mwh: float               # max(0, min_offtake_mwh − allocated_mwh)
    binding: list[str]
    binding_primary: str               # farm_supply|customer_demand|contract_cap|none|not_in_force
    reason: str                        # 引擎原文,可稽核
    headroom: bool
    farm_unallocated_mwh: float
    customer_unmet_mwh: float

    # 金額（has_price=False 時全為 None）
    price_per_kwh: float | None        # CPI 調整後
    energy_cost: float | None
    wheeling_fee: float | None
    take_or_pay_charge: float | None
    buyer_payable: float | None
    seller_receivable: float | None
    retailer_margin: float | None


class ContractYearTotals(BaseModel):
    months_in_force: int
    allocated_mwh: float
    cap_mwh: float | None              # 生效月份的上限加總；任一生效月未設上限則為 None
    utilization_percent: float | None
    min_offtake_mwh: float
    shortfall_mwh: float
    shortfall_months: int
    binding_counts: dict[str, int]     # 12 個月的 binding_primary 分佈,總和恆為 12
    headroom_months: int
    energy_cost: float | None
    wheeling_fee: float | None
    take_or_pay_charge: float | None
    buyer_payable: float | None
    seller_receivable: float | None
    retailer_margin: float | None
    margin_percent: float | None       # 毛利／買方應付 × 100；買方應付為 0 時為 None
    carbon_avoided_tco2e: float


class ContractDetail(BaseModel):
    contract_id: int
    contract_number: str
    year: int
    status: str
    priority: int
    start_date: date
    end_date: date
    wind_farm_id: int
    wind_farm_code: str
    wind_farm_name: str
    customer_id: int
    customer_code: str
    company_name: str

    # 條款
    contracted_energy_mwh: float | None
    contracted_percentage: float | None
    monthly_shares: list[float] | None            # 原始權重
    monthly_share_fractions: list[float] | None   # 正規化後的 12 個占比,供繪圖
    min_offtake_percent: float | None
    price_escalation_percent: float | None
    price_base_year: int | None
    base_price_per_kwh: float | None
    higher_priority_sibling_count: int            # 同案場、該年度有效、優先序更高的合約數

    # 計價前提（全部外顯,不藏預設值）
    has_price: bool
    used_default_feed_in: bool
    feed_in_price_per_kwh: float
    wheeling_fee_per_kwh: float
    grid_emission_factor_kg_per_kwh: float

    has_period_data: bool              # 該年度是否有任何發電或用電資料
    months: list[ContractMonth]        # 恆為 12 筆
    totals: ContractYearTotals
```

- [ ] **Step 2: 寫失敗的測試**

**先把新 import 併到 `tests/unit/test_contract_detail.py` 檔案最上方**，取代 Task 1 寫的那段 import（模組層 import 寫在檔案中段會被 ruff 判 E402）：

```python
from __future__ import annotations

import calendar
from datetime import date

import pytest

from app.models import ConsumptionData, Contract, Customer, GenerationData, WindFarm
from app.models.enums import ContractStatus
from app.services.contract_detail_service import (
    classify_binding,
    compute_contract_detail,
    has_headroom,
)
```

然後在檔案尾端追加：

```python
WIND_SHAPE = [1.35, 1.25, 1.05, 0.85, 0.70, 0.55, 0.55, 0.60, 0.85, 1.15, 1.30, 1.40]


def _month_bounds(year: int, month: int) -> tuple[date, date]:
    last = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last)


def _build(db, **contract_kw):
    """一場一戶一約,整年每月發電 3000 MWh、用電 5000 MWh。"""
    farm = WindFarm(
        code="WF-T", name="測試風場", installed_capacity_mw=100,
        feed_in_price_per_kwh=4.0,
    )
    cust = Customer(code="CU-T", company_name="測試用電廠", re_target_percent=50.0)
    db.add_all([farm, cust])
    db.flush()
    for m in range(1, 13):
        start, end = _month_bounds(2024, m)
        db.add(GenerationData(
            wind_farm_id=farm.id, period_start=start, period_end=end,
            generated_energy_mwh=3000.0, data_source="test",
        ))
        db.add(ConsumptionData(
            customer_id=cust.id, period_start=start, period_end=end,
            consumed_energy_mwh=5000.0, data_source="test",
        ))
    kw = {
        "contract_number": "PPA-T-1",
        "wind_farm_id": farm.id,
        "customer_id": cust.id,
        "start_date": date(2024, 1, 1),
        "end_date": date(2030, 12, 31),
        "contracted_energy_mwh": 12000.0,
        "price_per_kwh": 5.0,
        "priority": 1,
        "status": ContractStatus.ACTIVE,
    }
    kw.update(contract_kw)
    contract = Contract(**kw)
    db.add(contract)
    db.commit()
    return contract, farm, cust


def test_returns_twelve_months(db):
    contract, _, _ = _build(db)
    d = compute_contract_detail(db, contract.id, 2024)
    assert len(d.months) == 12
    assert [m.month for m in d.months] == list(range(1, 13))
    assert d.months[2].period == "2024-03"
    assert d.has_period_data is True


def test_flat_annual_volume_spreads_evenly(db):
    contract, _, _ = _build(db)
    d = compute_contract_detail(db, contract.id, 2024)
    assert all(m.cap_mwh == pytest.approx(1000.0) for m in d.months)
    assert d.months[0].cap_source == "volume"


def test_monthly_shares_shape_the_cap(db):
    contract, _, _ = _build(db, monthly_shares=WIND_SHAPE)
    d = compute_contract_detail(db, contract.id, 2024)
    total = sum(WIND_SHAPE)
    assert d.months[0].cap_mwh == pytest.approx(12000.0 * WIND_SHAPE[0] / total)
    assert d.months[5].cap_mwh == pytest.approx(12000.0 * WIND_SHAPE[5] / total)
    assert d.months[0].cap_mwh > d.months[5].cap_mwh  # 冬高夏低
    assert d.monthly_share_fractions is not None
    assert sum(d.monthly_share_fractions) == pytest.approx(1.0)


def test_no_monthly_shares_means_no_fractions(db):
    contract, _, _ = _build(db)
    assert compute_contract_detail(db, contract.id, 2024).monthly_share_fractions is None


def test_uncapped_contract_keeps_utilization_null(db):
    """未設上限 ≠ 使用率 0%。null 不能變成數字。"""
    contract, _, _ = _build(db, contracted_energy_mwh=None, contracted_percentage=None)
    d = compute_contract_detail(db, contract.id, 2024)
    assert all(m.cap_mwh is None for m in d.months)
    assert all(m.utilization_percent is None for m in d.months)
    assert d.months[0].cap_source == "none"
    assert d.totals.cap_mwh is None
    assert d.totals.utilization_percent is None


def test_percentage_cap_tracks_generation(db):
    contract, _, _ = _build(db, contracted_energy_mwh=None, contracted_percentage=50.0)
    d = compute_contract_detail(db, contract.id, 2024)
    assert all(m.cap_mwh == pytest.approx(1500.0) for m in d.months)
    assert d.months[0].cap_source == "percentage"


def test_take_or_pay_floor_and_shortfall(db):
    """年電量 36000（月 3000）> 案場月發電 3000 → 拿滿 3000,門檻 90% = 2700,不差額。"""
    contract, _, _ = _build(db, contracted_energy_mwh=36000.0, min_offtake_percent=90.0)
    d = compute_contract_detail(db, contract.id, 2024)
    assert d.months[0].min_offtake_mwh == pytest.approx(2700.0)
    assert d.months[0].shortfall_mwh == pytest.approx(0.0)
    assert d.totals.shortfall_months == 0


def test_shortfall_is_reported_when_supply_falls_short(db):
    """年電量 60000（月 5000）,案場只發 3000 → 門檻 4500,每月差額 1500。"""
    contract, _, _ = _build(db, contracted_energy_mwh=60000.0, min_offtake_percent=90.0)
    d = compute_contract_detail(db, contract.id, 2024)
    assert d.months[0].allocated_mwh == pytest.approx(3000.0)
    assert d.months[0].shortfall_mwh == pytest.approx(1500.0)
    assert d.totals.shortfall_months == 12
    assert d.totals.shortfall_mwh == pytest.approx(18000.0)


def test_out_of_force_months_are_not_zero_allocations(db):
    """2025 才生效的合約,2024 的每個月是「未生效」而不是「拿了 0」。"""
    contract, _, _ = _build(db, start_date=date(2025, 1, 1))
    d = compute_contract_detail(db, contract.id, 2024)
    assert all(m.in_force is False for m in d.months)
    assert all(m.binding_primary == "not_in_force" for m in d.months)
    assert all(m.binding == [] for m in d.months)
    assert all(m.cap_mwh is None for m in d.months)
    assert all(m.skip_reason for m in d.months)
    assert d.totals.months_in_force == 0
    assert d.totals.allocated_mwh == pytest.approx(0.0)


def test_binding_counts_cover_all_twelve_months(db):
    contract, _, _ = _build(db)
    d = compute_contract_detail(db, contract.id, 2024)
    assert sum(d.totals.binding_counts.values()) == 12


def test_annual_totals_equal_the_sum_of_months(db):
    """年度合計必須就是 12 個月加總——這個專案栽過加總錯誤的跟頭。"""
    contract, _, _ = _build(db, contracted_energy_mwh=60000.0, min_offtake_percent=90.0)
    d = compute_contract_detail(db, contract.id, 2024)
    assert d.totals.allocated_mwh == pytest.approx(sum(m.allocated_mwh for m in d.months))
    assert d.totals.shortfall_mwh == pytest.approx(sum(m.shortfall_mwh for m in d.months))
    assert d.totals.min_offtake_mwh == pytest.approx(sum(m.min_offtake_mwh for m in d.months))


def test_higher_priority_siblings_are_counted(db):
    contract, farm, cust = _build(db, priority=3)
    db.add(Contract(
        contract_number="PPA-T-2", wind_farm_id=farm.id, customer_id=cust.id,
        start_date=date(2024, 1, 1), end_date=date(2030, 12, 31),
        contracted_percentage=50.0, price_per_kwh=5.0, priority=1,
        status=ContractStatus.ACTIVE,
    ))
    db.commit()
    d = compute_contract_detail(db, contract.id, 2024)
    assert d.higher_priority_sibling_count == 1


def test_top_priority_contract_has_no_higher_siblings(db):
    """本合約已是該案場最高優先序時必須是 0——否則畫面會憑空指控它被插隊。"""
    contract, _, _ = _build(db, priority=1)
    assert compute_contract_detail(db, contract.id, 2024).higher_priority_sibling_count == 0


def test_year_without_measurements_is_flagged(db):
    contract, _, _ = _build(db)
    d = compute_contract_detail(db, contract.id, 2023)
    assert d.has_period_data is False
    assert len(d.months) == 12


def test_unknown_contract_raises_not_found(db):
    from app.core.exceptions import NotFoundError

    with pytest.raises(NotFoundError):
        compute_contract_detail(db, 9999, 2024)
```

- [ ] **Step 3: 跑測試確認失敗**

Run: `.venv/bin/pytest tests/unit/test_contract_detail.py -q`
Expected: FAIL — `ImportError: cannot import name 'compute_contract_detail'`

- [ ] **Step 4: 實作 service**

在 `app/services/contract_detail_service.py` 的 import 區塊加：

```python
from collections import Counter
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.matching import MatchingOutcome
from app.matching.contract_terms import (
    min_offtake_mwh,
    monthly_share,
    monthly_volume_cap,
)
from app.models import ConsumptionData, Contract, Customer, GenerationData, WindFarm
from app.models.enums import ContractStatus
from app.schemas.contract_detail import (
    ContractDetail,
    ContractMonth,
    ContractYearTotals,
)
from app.services import contracts as contract_svc
from app.services.matching_service import compute_outcome
```

在檔案尾端加：

```python
def _cap_source(contract: Contract) -> str:
    """這紙合約設了哪些上限——12 個月皆同,與當月有沒有生效無關。"""
    has_volume = contract.contracted_energy_mwh is not None
    has_percent = contract.contracted_percentage is not None
    if has_volume and has_percent:
        return "both"
    if has_volume:
        return "volume"
    if has_percent:
        return "percentage"
    return "none"


def _has_period_data(db: Session, year: int) -> bool:
    """該年度有沒有任何發電或用電量測。沒有的話整頁的圖都不該畫。"""
    start, end = date(year, 1, 1), date(year, 12, 31)
    gen = db.scalar(
        select(func.count())
        .select_from(GenerationData)
        .where(GenerationData.period_start >= start, GenerationData.period_start <= end)
    )
    con = db.scalar(
        select(func.count())
        .select_from(ConsumptionData)
        .where(
            ConsumptionData.period_start >= start, ConsumptionData.period_start <= end
        )
    )
    return bool(gen) or bool(con)


def _higher_priority_siblings(db: Session, contract: Contract, year: int) -> int:
    """同案場、該年度內任一時點有效、且優先序嚴格更高的合約數。

    畫面用它決定要不要說「本合約被插隊」——本合約已是最高優先序時這句話是錯的。
    """
    start, end = date(year, 1, 1), date(year, 12, 31)
    return (
        db.scalar(
            select(func.count())
            .select_from(Contract)
            .where(
                Contract.wind_farm_id == contract.wind_farm_id,
                Contract.id != contract.id,
                Contract.status == ContractStatus.ACTIVE,
                Contract.priority < contract.priority,
                Contract.start_date <= end,
                Contract.end_date >= start,
            )
        )
        or 0
    )


def _month_context(
    outcome: MatchingOutcome, contract: Contract
) -> tuple[float, float]:
    """本月案場還剩多少未分配、客戶還有多少沒被滿足——加購空間判定的兩個前提。"""
    farm = next(
        (f for f in outcome.farm_summaries if f.farm_id == contract.wind_farm_id), None
    )
    cust = next(
        (c for c in outcome.customer_summaries if c.customer_id == contract.customer_id),
        None,
    )
    farm_left = max(0.0, farm.unallocated_mwh) if farm else 0.0
    cust_unmet = (
        max(0.0, cust.consumption_mwh - cust.allocated_mwh) if cust else 0.0
    )
    return farm_left, cust_unmet


def _not_in_force_month(
    period: str, month: int, reason: str, cap_source: str,
    farm_left: float, cust_unmet: float,
) -> ContractMonth:
    """未生效／已到期的月份。分配是 None 語意,不是 0——這格講錯整頁就毀了。"""
    return ContractMonth(
        period=period, month=month, in_force=False, skip_reason=reason,
        cap_mwh=None, cap_source=cap_source, allocated_mwh=0.0,
        utilization_percent=None, min_offtake_mwh=0.0, shortfall_mwh=0.0,
        binding=[], binding_primary="not_in_force", reason=reason, headroom=False,
        farm_unallocated_mwh=round(farm_left, 6),
        customer_unmet_mwh=round(cust_unmet, 6),
        price_per_kwh=None, energy_cost=None, wheeling_fee=None,
        take_or_pay_charge=None, buyer_payable=None, seller_receivable=None,
        retailer_margin=None,
    )


def _build_months(
    db: Session, contract: Contract, year: int, cap_source: str
) -> list[ContractMonth]:
    months: list[ContractMonth] = []
    for m in range(1, 13):
        period = f"{year}-{m:02d}"
        outcome = compute_outcome(db, period)
        farm_left, cust_unmet = _month_context(outcome, contract)
        alloc = next(
            (a for a in outcome.allocations if a.contract_id == contract.id), None
        )
        if alloc is None:
            skipped = next(
                (s for s in outcome.skipped if s.contract_id == contract.id), None
            )
            months.append(
                _not_in_force_month(
                    period, m,
                    skipped.reason if skipped else "contract not in this period",
                    cap_source, farm_left, cust_unmet,
                )
            )
            continue

        cap = alloc.contract_limit_mwh
        binding, primary = classify_binding(alloc.reason)
        floor = min_offtake_mwh(
            monthly_volume_cap(
                contract.contracted_energy_mwh, contract.monthly_shares, m
            ),
            contract.min_offtake_percent,
        )
        months.append(
            ContractMonth(
                period=period, month=m, in_force=True, skip_reason=None,
                cap_mwh=None if cap is None else round(cap, 6),
                cap_source=cap_source,
                allocated_mwh=round(alloc.allocated_mwh, 6),
                utilization_percent=(
                    round(alloc.allocated_mwh / cap * 100.0, 6) if cap else None
                ),
                min_offtake_mwh=round(floor, 6),
                shortfall_mwh=round(max(0.0, floor - alloc.allocated_mwh), 6),
                binding=binding, binding_primary=primary, reason=alloc.reason,
                headroom=has_headroom(primary, farm_left, cust_unmet),
                farm_unallocated_mwh=round(farm_left, 6),
                customer_unmet_mwh=round(cust_unmet, 6),
                price_per_kwh=None, energy_cost=None, wheeling_fee=None,
                take_or_pay_charge=None, buyer_payable=None,
                seller_receivable=None, retailer_margin=None,
            )
        )
    return months


def _build_totals(months: list[ContractMonth], factor: float) -> ContractYearTotals:
    in_force = [m for m in months if m.in_force]
    allocated = sum(m.allocated_mwh for m in in_force)
    caps = [m.cap_mwh for m in in_force]
    total_cap = (
        sum(c for c in caps if c is not None)
        if caps and all(c is not None for c in caps)
        else None
    )
    return ContractYearTotals(
        months_in_force=len(in_force),
        allocated_mwh=round(allocated, 6),
        cap_mwh=None if total_cap is None else round(total_cap, 6),
        utilization_percent=(
            round(allocated / total_cap * 100.0, 6) if total_cap else None
        ),
        min_offtake_mwh=round(sum(m.min_offtake_mwh for m in in_force), 6),
        shortfall_mwh=round(sum(m.shortfall_mwh for m in in_force), 6),
        shortfall_months=sum(1 for m in in_force if m.shortfall_mwh > EPS),
        binding_counts=dict(Counter(m.binding_primary for m in months)),
        headroom_months=sum(1 for m in months if m.headroom),
        energy_cost=None, wheeling_fee=None, take_or_pay_charge=None,
        buyer_payable=None, seller_receivable=None, retailer_margin=None,
        margin_percent=None,
        carbon_avoided_tco2e=round(allocated * factor, 6),
    )


def compute_contract_detail(
    db: Session, contract_id: int, year: int
) -> ContractDetail:
    """一紙合約在 ``year`` 這一年的逐月履約與雙面帳。

    以 ``match_period``（合約優先序）為基準,不是 ``optimize_period``——履約講的是
    「依約該拿到什麼」,不是「最佳化後會拿到什麼」。因此本頁金額與轉供結算單頁
    會有落差,頁面上會註明。
    """
    contract = contract_svc.get(db, contract_id)
    farm = db.get(WindFarm, contract.wind_farm_id)
    customer = db.get(Customer, contract.customer_id)
    cap_source = _cap_source(contract)

    feed_in = farm.feed_in_price_per_kwh if farm else None
    used_default_feed_in = feed_in is None
    if feed_in is None:
        feed_in = settings.default_feed_in_price_per_kwh

    months = _build_months(db, contract, year, cap_source)
    totals = _build_totals(months, settings.grid_emission_factor_kg_per_kwh)

    shares = contract.monthly_shares
    return ContractDetail(
        contract_id=contract.id,
        contract_number=contract.contract_number,
        year=year,
        status=contract.status.value,
        priority=contract.priority,
        start_date=contract.start_date,
        end_date=contract.end_date,
        wind_farm_id=contract.wind_farm_id,
        wind_farm_code=farm.code if farm else str(contract.wind_farm_id),
        wind_farm_name=(farm.name if farm else "") or "",
        customer_id=contract.customer_id,
        customer_code=customer.code if customer else str(contract.customer_id),
        company_name=(customer.company_name if customer else "") or "",
        contracted_energy_mwh=contract.contracted_energy_mwh,
        contracted_percentage=contract.contracted_percentage,
        monthly_shares=shares,
        monthly_share_fractions=(
            [monthly_share(shares, m) for m in range(1, 13)] if shares else None
        ),
        min_offtake_percent=contract.min_offtake_percent,
        price_escalation_percent=contract.price_escalation_percent,
        price_base_year=contract.price_base_year,
        base_price_per_kwh=contract.price_per_kwh,
        higher_priority_sibling_count=_higher_priority_siblings(db, contract, year),
        has_price=contract.price_per_kwh is not None,
        used_default_feed_in=used_default_feed_in,
        feed_in_price_per_kwh=feed_in,
        wheeling_fee_per_kwh=settings.wheeling_fee_per_kwh,
        grid_emission_factor_kg_per_kwh=settings.grid_emission_factor_kg_per_kwh,
        has_period_data=_has_period_data(db, year),
        months=months,
        totals=totals,
    )
```

- [ ] **Step 5: 跑測試確認通過**

Run: `.venv/bin/pytest tests/unit/test_contract_detail.py -q`
Expected: PASS

- [ ] **Step 6: 跑閘門**

```bash
.venv/bin/ruff check app tests && .venv/bin/black --check app tests && .venv/bin/mypy app && .venv/bin/pytest -q
```
Expected: 全綠

- [ ] **Step 7: Commit**

```bash
git add app/schemas/contract_detail.py app/services/contract_detail_service.py tests/unit/test_contract_detail.py
git commit -m "$(cat <<'EOF'
feat(contracts): project one contract's year into a monthly fulfilment series

Runs the existing monthly engine twelve times and pulls out one contract's
row: the month's cap, what it actually got, which constraint bound it, and
how far it fell below any take-or-pay floor.

Two distinctions the schema refuses to blur. A month the contract was not in
force reports in_force=False with the engine's own skip reason, not a zero
allocation — "got nothing" and "was not running" are different facts. And an
uncapped contract reports cap_mwh=None with utilization_percent=None rather
than 0, because "no cap" is not "used none of it".

Money fields are declared but left None; the next commit fills them.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: 雙面帳金額

公式逐字沿用 `app/services/settlement_service.py:113-124`，只是把作用範圍從「客戶」縮到「這紙合約」。**刻意用同一條公式，是為了讓本頁與結算單頁的差異只剩「引擎不同」這一個變數。**

**Files:**
- Modify: `app/services/contract_detail_service.py`
- Test: `tests/unit/test_contract_detail.py`

**Interfaces:**
- Consumes: Task 2 的 `_build_months()` / `_build_totals()` / `compute_contract_detail()`
- Produces: `ContractMonth` 與 `ContractYearTotals` 的金額欄位填入實值（`has_price=False` 時維持 `None`）

- [ ] **Step 1: 寫失敗的測試**

在 `tests/unit/test_contract_detail.py` 尾端追加：

```python
def test_money_identities_hold_every_month(db):
    """兩條恆等式。公式跟結算單同一套,差異只該來自引擎不同。"""
    contract, _, _ = _build(db, contracted_energy_mwh=60000.0, min_offtake_percent=90.0)
    d = compute_contract_detail(db, contract.id, 2024)
    for m in d.months:
        assert m.buyer_payable == pytest.approx(
            m.energy_cost + m.wheeling_fee + m.take_or_pay_charge
        )
        assert m.retailer_margin == pytest.approx(
            m.energy_cost - m.seller_receivable - m.wheeling_fee + m.take_or_pay_charge
        )


def test_money_uses_contract_price_and_farm_feed_in(db):
    """月 3000 MWh × 5.0 元 = 1500 萬綠電費；應收 3000 MWh × 4.0 元 = 1200 萬。"""
    contract, _, _ = _build(db, contracted_energy_mwh=36000.0)
    d = compute_contract_detail(db, contract.id, 2024)
    jan = d.months[0]
    assert jan.allocated_mwh == pytest.approx(3000.0)
    assert jan.price_per_kwh == pytest.approx(5.0)
    assert jan.energy_cost == pytest.approx(3000.0 * 1000 * 5.0)
    assert jan.seller_receivable == pytest.approx(3000.0 * 1000 * 4.0)
    assert jan.wheeling_fee == pytest.approx(3000.0 * 1000 * d.wheeling_fee_per_kwh)


def test_cpi_escalates_the_price_by_year(db):
    contract, _, _ = _build(
        db, price_escalation_percent=2.5, price_base_year=2022,
    )
    d = compute_contract_detail(db, contract.id, 2024)
    assert d.months[0].price_per_kwh == pytest.approx(5.0 * 1.025**2)


def test_price_before_the_base_year_is_not_discounted(db):
    contract, _, _ = _build(db, price_escalation_percent=2.5, price_base_year=2030)
    d = compute_contract_detail(db, contract.id, 2024)
    assert d.months[0].price_per_kwh == pytest.approx(5.0)


def test_contract_without_a_price_reports_no_money_at_all(db):
    """不拿躉售價代入讓毛利變成 0——那是個看起來合理但不真實的數字。"""
    contract, _, _ = _build(db, price_per_kwh=None)
    d = compute_contract_detail(db, contract.id, 2024)
    assert d.has_price is False
    for m in d.months:
        assert m.price_per_kwh is None
        assert m.energy_cost is None
        assert m.buyer_payable is None
        assert m.retailer_margin is None
    assert d.totals.buyer_payable is None
    assert d.totals.margin_percent is None


def test_farm_without_a_feed_in_price_is_flagged(db):
    contract, farm, _ = _build(db)
    farm.feed_in_price_per_kwh = None
    db.commit()
    d = compute_contract_detail(db, contract.id, 2024)
    assert d.used_default_feed_in is True
    assert d.feed_in_price_per_kwh > 0


def test_annual_money_equals_the_sum_of_months(db):
    contract, _, _ = _build(db, contracted_energy_mwh=60000.0, min_offtake_percent=90.0)
    d = compute_contract_detail(db, contract.id, 2024)
    t = d.totals
    assert t.buyer_payable == pytest.approx(sum(m.buyer_payable for m in d.months))
    assert t.seller_receivable == pytest.approx(
        sum(m.seller_receivable for m in d.months)
    )
    assert t.retailer_margin == pytest.approx(sum(m.retailer_margin for m in d.months))
    assert t.margin_percent == pytest.approx(t.retailer_margin / t.buyer_payable * 100)


def test_out_of_force_months_cost_nothing_but_are_not_null(db):
    """有售電價的合約,未生效月份金額是 0（可加總）,不是 None。"""
    contract, _, _ = _build(db, start_date=date(2025, 1, 1))
    d = compute_contract_detail(db, contract.id, 2024)
    assert all(m.buyer_payable == 0.0 for m in d.months)
    assert d.totals.margin_percent is None  # 應付為 0 → 毛利率無意義
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `.venv/bin/pytest tests/unit/test_contract_detail.py -q`
Expected: FAIL — `TypeError: unsupported operand type(s) for +: 'NoneType' and 'NoneType'`（金額仍為 None）

- [ ] **Step 3: 加入金額計算**

在 `app/services/contract_detail_service.py` 的 import 區塊補上 `dataclass` 與 `effective_price`：

```python
from dataclasses import dataclass
```

```python
from app.matching.contract_terms import (
    effective_price,
    min_offtake_mwh,
    monthly_share,
    monthly_volume_cap,
)
```

在 `EPS` 常數之後、`_cap_source` 之前加入計價常數與 dataclass：

```python
_KWH = 1000.0


@dataclass(frozen=True)
class _Pricing:
    """一年份的計價前提。售電價經 CPI 調整後全年同一個值。"""

    price_per_kwh: float | None   # None = 合約未設售電價
    feed_in_per_kwh: float
    wheeling_per_kwh: float
```

在 `_not_in_force_month` 之後加入：

```python
def _money(
    pricing: _Pricing, allocated_mwh: float, shortfall_mwh: float
) -> dict[str, float | None]:
    """單月三方金額。公式沿用 ``settlement_service``,只是把範圍縮到這紙合約。

    所有費率都是 per-kWh,保證量門檻也是合約層級的——因此不需要任何
    「這紙合約該分攤客戶多少費用」之類的分攤假設。
    """
    if pricing.price_per_kwh is None:
        return {
            "price_per_kwh": None, "energy_cost": None, "wheeling_fee": None,
            "take_or_pay_charge": None, "buyer_payable": None,
            "seller_receivable": None, "retailer_margin": None,
        }
    kwh = allocated_mwh * _KWH
    energy_cost = kwh * pricing.price_per_kwh
    wheeling_fee = kwh * pricing.wheeling_per_kwh
    top_charge = shortfall_mwh * _KWH * pricing.price_per_kwh
    seller = kwh * pricing.feed_in_per_kwh
    return {
        "price_per_kwh": round(pricing.price_per_kwh, 6),
        "energy_cost": round(energy_cost, 2),
        "wheeling_fee": round(wheeling_fee, 2),
        "take_or_pay_charge": round(top_charge, 2),
        "buyer_payable": round(energy_cost + wheeling_fee + top_charge, 2),
        "seller_receivable": round(seller, 2),
        "retailer_margin": round(energy_cost - seller - wheeling_fee + top_charge, 2),
    }
```

`_not_in_force_month` 與 `_build_months` 都改為接受 `pricing` 並套用 `_money(...)`：

```python
def _not_in_force_month(
    period: str, month: int, reason: str, cap_source: str,
    farm_left: float, cust_unmet: float, pricing: _Pricing,
) -> ContractMonth:
    """未生效／已到期的月份。分配是 None 語意,不是 0——這格講錯整頁就毀了。"""
    return ContractMonth(
        period=period, month=month, in_force=False, skip_reason=reason,
        cap_mwh=None, cap_source=cap_source, allocated_mwh=0.0,
        utilization_percent=None, min_offtake_mwh=0.0, shortfall_mwh=0.0,
        binding=[], binding_primary="not_in_force", reason=reason, headroom=False,
        farm_unallocated_mwh=round(farm_left, 6),
        customer_unmet_mwh=round(cust_unmet, 6),
        **_money(pricing, 0.0, 0.0),
    )
```

`_build_months(db, contract, year, cap_source)` 改成 `_build_months(db, contract, year, cap_source, pricing)`；未生效分支傳入 `pricing`；生效分支把七個 `xxx=None` 換成：

```python
                **_money(pricing, alloc.allocated_mwh, max(0.0, floor - alloc.allocated_mwh)),
```

`_build_totals(months, factor)` 改成 `_build_totals(months, factor, has_price)`，並把六個金額欄位與 `margin_percent` 換成：

```python
    def total(field: str) -> float | None:
        if not has_price:
            return None
        return round(sum(getattr(m, field) or 0.0 for m in months), 2)

    buyer = total("buyer_payable")
    margin = total("retailer_margin")
    ...
        energy_cost=total("energy_cost"),
        wheeling_fee=total("wheeling_fee"),
        take_or_pay_charge=total("take_or_pay_charge"),
        buyer_payable=buyer,
        seller_receivable=total("seller_receivable"),
        retailer_margin=margin,
        margin_percent=(
            round(margin / buyer * 100.0, 6)
            if buyer and margin is not None
            else None
        ),
```

`compute_contract_detail` 裡建立 `pricing` 並傳下去：

```python
    pricing = _Pricing(
        price_per_kwh=(
            effective_price(
                contract.price_per_kwh,
                contract.price_escalation_percent,
                contract.price_base_year,
                year,
            )
            if contract.price_per_kwh is not None
            else None
        ),
        feed_in_per_kwh=feed_in,
        wheeling_per_kwh=settings.wheeling_fee_per_kwh,
    )
    months = _build_months(db, contract, year, cap_source, pricing)
    totals = _build_totals(
        months,
        settings.grid_emission_factor_kg_per_kwh,
        contract.price_per_kwh is not None,
    )
```

- [ ] **Step 4: 跑測試確認通過**

Run: `.venv/bin/pytest tests/unit/test_contract_detail.py -q`
Expected: PASS

- [ ] **Step 5: 跑閘門**

```bash
.venv/bin/ruff check app tests && .venv/bin/black --check app tests && .venv/bin/mypy app && .venv/bin/pytest -q
```
Expected: 全綠

- [ ] **Step 6: Commit**

```bash
git add app/services/contract_detail_service.py tests/unit/test_contract_detail.py
git commit -m "$(cat <<'EOF'
feat(contracts): compute the two-sided bill per contract

Buyer payable, farm receivable and retailer margin for one contract, month by
month. The formula is copied verbatim from settlement_service so that when
this page and the settlement page disagree, the only possible cause is the
allocation engine — not two separate implementations of the arithmetic.

No apportionment assumptions are needed: every rate is per-kWh and the
take-or-pay floor is already contract-level, so nothing has to be split out
of a customer-level total.

A contract with no sale price reports every money field as None rather than
substituting the feed-in tariff, which would silently render margin as zero.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: API 端點與 api.js

**Files:**
- Modify: `app/api/v1/analytics.py`
- Modify: `web/api.js:169`（在 `customerOptimization` 後面）
- Test: `tests/integration/test_contract_detail_api.py`

**Interfaces:**
- Consumes: `compute_contract_detail()`（Task 3）
- Produces:
  - `GET /api/v1/analytics/contract-detail?contract_id={int}&year={int}` → `ContractDetail`
  - `api.contractDetail(contractId, year) -> Promise<ContractDetail>`

- [ ] **Step 1: 寫失敗的測試**

建立 `tests/integration/test_contract_detail_api.py`：

```python
"""合約詳情端點。除了 happy path,也對示範資料釘住兩個具體事實——
它們是這一頁存在的理由,壞掉時要在 CI 就看到。"""

from __future__ import annotations


def _detail(client, number: str, year: int = 2024):
    contracts = client.get("/api/v1/contracts?limit=1000").json()
    cid = next(c["id"] for c in contracts if c["contract_number"] == number)
    resp = client.get(
        f"/api/v1/analytics/contract-detail?contract_id={cid}&year={year}"
    )
    assert resp.status_code == 200
    return resp.json()


def test_contract_detail_endpoint(client, seeded_db):
    d = _detail(client, "PPA-2022-005")
    assert len(d["months"]) == 12
    assert d["has_period_data"] is True
    assert d["has_price"] is True
    assert sum(d["totals"]["binding_counts"].values()) == 12


def test_unknown_contract_is_404(client, seeded_db):
    resp = client.get("/api/v1/analytics/contract-detail?contract_id=9999&year=2024")
    assert resp.status_code == 404


def test_year_without_data_still_returns_the_terms(client, seeded_db):
    d = _detail(client, "PPA-2022-005", year=2030)
    assert d["has_period_data"] is False
    assert len(d["months"]) == 12
    assert d["contracted_energy_mwh"] == 15000.0


def test_sample_contract_004_is_supply_bound_all_year(client, seeded_db):
    """FORMOSA2 上排在優先序 3,前面的合約把電吃光——這是頁面上最有話講的一種。"""
    d = _detail(client, "PPA-2024-004")
    assert all(m["binding_primary"] == "farm_supply" for m in d["months"])
    assert d["higher_priority_sibling_count"] > 0
    assert all(m["headroom"] is False for m in d["months"])


def test_sample_contract_005_never_triggers_take_or_pay(client, seeded_db):
    """保證量 80%,但每月都拿滿上限 → 全年零差額。頁面要照實寫「未觸發」。"""
    d = _detail(client, "PPA-2022-005")
    assert d["min_offtake_percent"] == 80.0
    assert d["totals"]["shortfall_mwh"] == 0.0
    assert d["totals"]["shortfall_months"] == 0


def test_pending_contract_is_out_of_force_not_zero(client, seeded_db):
    d = _detail(client, "PPA-2025-008")
    assert all(m["in_force"] is False for m in d["months"])
    assert all(m["binding_primary"] == "not_in_force" for m in d["months"])
    assert d["monthly_share_fractions"] is not None  # 條款照樣要看得到
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `.venv/bin/pytest tests/integration/test_contract_detail_api.py -q`
Expected: FAIL — 404（路由不存在）

- [ ] **Step 3: 加端點**

在 `app/api/v1/analytics.py` 的 import 區塊加：

```python
from app.schemas.contract_detail import ContractDetail
from app.services import contract_detail_service as contract_detail_svc
```

在檔案尾端（`re_recommendations` 之後）加：

```python
@router.get("/contract-detail", response_model=ContractDetail)
def contract_detail(
    contract_id: int = Query(..., ge=1),
    year: int = Query(..., ge=2000, le=2100),
    db: Session = Depends(get_db),
) -> ContractDetail:
    """One contract's year: monthly fulfilment, binding constraint, two-sided bill."""
    return contract_detail_svc.compute_contract_detail(db, contract_id, year)
```

不掛 `solver_slot`——本端點走的是 `match_period`，不進 MILP 求解器。

- [ ] **Step 4: 加 api.js**

在 `web/api.js` 的 `customerOptimization` 之後（`};` 之前）加：

```js
    contractDetail: function (contractId, year) {
      return get("/analytics/contract-detail", { contract_id: contractId, year: year });
    },
```

- [ ] **Step 5: 跑測試確認通過**

Run: `.venv/bin/pytest tests/integration/test_contract_detail_api.py -q`
Expected: PASS

- [ ] **Step 6: 跑閘門**

```bash
.venv/bin/ruff check app tests && .venv/bin/black --check app tests && .venv/bin/mypy app && .venv/bin/pytest -q && node --check web/api.js
```
Expected: 全綠

- [ ] **Step 7: Commit**

```bash
git add app/api/v1/analytics.py web/api.js tests/integration/test_contract_detail_api.py
git commit -m "$(cat <<'EOF'
feat(api): expose GET /analytics/contract-detail

Read-only, no solver slot — this path runs the priority engine, not the MILP.

The integration tests pin two facts about the sample data rather than only
the happy path: PPA-2024-004 is supply-bound every month of 2024 (it sits at
priority 3 behind two contracts on the same farm), and PPA-2022-005 never
trips its 80% take-or-pay floor. Both are the cases the page was designed
around, so a change that quietly flattens them should fail CI.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: 前端骨架 — 路由、頁首、① 全年被什麼卡住、⑤ 合約條款

這個 task 完成後合約清單就點得進去，看得到結論句與條款。圖表與金額在 Task 6/7。

**Files:**
- Modify: `web/app.js`（路由表 `:127-134`、`NAV_PARENT :88`、`renderContracts :427-435`、綠電合約區塊 `:405` 之後）
- Modify: `web/styles.css`

**Interfaces:**
- Consumes: `api.contractDetail()`（Task 4）
- Produces:
  - `BIND_META`（綁定約束 → CSS class 與中文名，Task 6 共用）
  - `bindStrip(months) -> string`
  - `bindVerdict(detail) -> string`
  - `contractTermsCard(detail) -> string`
  - `renderContractDetail()`
  - `renderContractDetailBody(body, detail, risks)`（Task 6/7 會往裡面加區塊）

- [ ] **Step 1: 讓清單列可點**

在 `web/app.js` 的 `renderContracts()` 內，把每一列的 `<tr>` 加上 `data-cid` 與可點樣式。將 `:429` 的

```js
          html += "<tr><td class=\"code\">" + esc(c.contract_number) + contractTerms(c) +
```

改為

```js
          html += '<tr class="clickrow" data-cid="' + c.id + '"><td class="code">' + esc(c.contract_number) + contractTerms(c) +
```

在同一函式內 `body.innerHTML = html;`（`:437`）之後加：

```js
        // 整列可點進詳情頁；編輯模式的操作鈕不算（點刪除不該跳頁）
        body.addEventListener("click", function (e) {
          if (e.target.closest("button") || e.target.closest("a")) return;
          var tr = e.target.closest(".clickrow");
          if (!tr) return;
          location.hash = "#/contract?id=" + tr.getAttribute("data-cid") +
            "&year=" + getPeriod().slice(0, 4);
        });
```

- [ ] **Step 2: 註冊路由**

在 `web/app.js:131` 的 views 物件內，`matchmap: renderMatchmap, cfe: renderCfe,` 之後加：

```js
      contract: renderContractDetail,
```

在 `:88` 的 `NAV_PARENT` 加一組對應，讓側欄的「綠電合約」保持高亮：

```js
  var NAV_PARENT = { meters: "customers", settlement: "evaluate", recommend: "matchmap", contract: "contracts" };
```

- [ ] **Step 3: 寫詳情頁骨架**

在 `web/app.js` 的 `contractCap()`（`:405`）之後、`renderContracts()` 之前插入：

```js
  // ---------- 合約詳情（商務視角） ----------
  // 綁定約束 → 顏色與說法。① 分佈條與 ② 月別圖共用同一套,免得兩處各講一套。
  var BIND_META = {
    contract_cap: { cls: "b-cap", name: "合約上限" },
    farm_supply: { cls: "b-sup", name: "案場供給" },
    customer_demand: { cls: "b-dem", name: "客戶用電" },
    none: { cls: "b-non", name: "無分配" },
    not_in_force: { cls: "b-nif", name: "未生效" },
  };
  function bindMeta(k) { return BIND_META[k] || BIND_META.none; }

  // 12 格分佈條 + 圖例。一格一個月,顏色就是那個月的主綁定約束。
  function bindStrip(months) {
    var cells = months.map(function (m) {
      var meta = bindMeta(m.binding_primary);
      return '<span class="bcell ' + meta.cls + '" title="' +
        esc(m.period + " · " + meta.name) + '">' + m.month + "</span>";
    }).join("");
    var counts = {}, order = [];
    months.forEach(function (m) {
      if (counts[m.binding_primary] == null) { counts[m.binding_primary] = 0; order.push(m.binding_primary); }
      counts[m.binding_primary]++;
    });
    var lg = order.map(function (k) {
      return '<span><i class="sw ' + bindMeta(k).cls + '"></i>' + esc(bindMeta(k).name) +
        " " + counts[k] + " 個月</span>";
    }).join("");
    return '<div class="bstrip">' + cells + "</div>" + '<div class="blg">' + lg + "</div>";
  }

  // 全年結論句。每個子句都有成立條件——條件不成立就不寫,不靠形容詞硬補。
  function bindVerdict(d) {
    var t = d.totals, counts = t.binding_counts || {}, top = null, n = -1;
    Object.keys(counts).forEach(function (k) { if (counts[k] > n) { n = counts[k]; top = k; } });
    if (top === "not_in_force") {
      return "本合約於 " + d.year + " 年度未生效或已到期,無實際分配。";
    }
    if (top === "contract_cap") {
      var s = n + " 個月被合約上限卡住";
      if (t.headroom_months > 0) {
        s += "——客戶的需求高於合約允許量,其中 " + t.headroom_months +
          " 個月案場仍有餘電,有加購空間";
      }
      return s + "。";
    }
    if (top === "farm_supply") {
      var f = n + " 個月被案場供給卡住——此案場已無餘電可分配";
      if (t.utilization_percent != null) {
        f += ",全年只拿到上限的 " + pct(t.utilization_percent, 0) + "%";
      }
      if (d.higher_priority_sibling_count > 0) {
        f += ";同案場另有 " + d.higher_priority_sibling_count + " 紙優先序更高的合約先分";
      }
      return f + "。";
    }
    if (top === "customer_demand") {
      return n + " 個月被客戶用電卡住——合約允許量高於客戶實際用得掉的量。";
    }
    return "該年度未取得任何分配,引擎未指出單一約束。";
  }

  // 月別配比小條圖。條款本身就是資料——未生效的年度也照畫。
  function sharesBar(fr) {
    if (!fr) return '<span class="u">未設,年電量平均 1/12 分攤</span>';
    var mx = Math.max.apply(null, fr) || 1;
    return '<div class="shbar">' + fr.map(function (v, i) {
      return '<span class="shcell" title="' + (i + 1) + " 月 " + (v * 100).toFixed(1) +
        '%"><i style="height:' + (v / mx * 100).toFixed(1) + '%"></i><b>' + (i + 1) + "</b></span>";
    }).join("") + "</div>";
  }

  // CPI 逐年單價。沒設漲幅就不畫——空表格比沒有更糟。
  function priceLadder(d) {
    if (d.price_escalation_percent == null || d.price_base_year == null ||
        d.base_price_per_kwh == null) return "";
    var y0 = parseInt(String(d.start_date).slice(0, 4), 10);
    var y1 = parseInt(String(d.end_date).slice(0, 4), 10);
    var out = [];
    for (var y = y0; y <= y1 && out.length < 12; y++) {
      var n = Math.max(0, y - d.price_base_year);
      out.push('<span class="pl"><b>' + y + "</b>" +
        price(d.base_price_per_kwh * Math.pow(1 + d.price_escalation_percent / 100, n)) + "</span>");
    }
    return '<div class="subhd"><span>逐年單價</span><small>基準年 ' + d.price_base_year +
      " · 每年 +" + pct(d.price_escalation_percent, 1) + "%</small></div>" +
      '<div class="pladder">' + out.join("") + "</div>";
  }

  function contractTermsCard(d) {
    var top = d.min_offtake_percent == null
      ? '<span class="u">無此條款</span>'
      : pct(d.min_offtake_percent, 0) + "%" +
        (d.totals.min_offtake_mwh > 0 && d.totals.shortfall_mwh === 0
          ? '<span class="u">全年皆達標,未觸發差額</span>' : "");
    return '<section class="card"><div class="hd"><h3>合約條款</h3>' +
      '<span class="aside">紙上寫的規則</span></div>' +
      '<div class="rows" style="padding:4px 18px 14px">' +
      erow("合約期間", esc(d.start_date) + " ～ " + esc(d.end_date)) +
      erow("優先序", String(d.priority)) +
      erow("合約上限", contractCap(d), "", "", null, "contractCap") +
      erow("售電價", d.base_price_per_kwh == null
        ? '<span class="u">未設</span>' : price(d.base_price_per_kwh), "NTD/kWh") +
      erow("保證量 (take-or-pay)", top) +
      "</div>" +
      '<div class="subhd"><span>月別配比</span><small>年電量如何攤到各月</small></div>' +
      '<div style="padding:0 18px 16px">' + sharesBar(d.monthly_share_fractions) + "</div>" +
      priceLadder(d) +
      "</section>";
  }

  function renderContractDetail() {
    var p = parseHash().params;
    var id = parseInt(p.id, 10);
    var year = parseInt(p.year, 10) || parseInt(getPeriod().slice(0, 4), 10);
    crumb.textContent = "合約詳情";
    if (!id) {
      view.innerHTML = errbox("合約詳情", new Error("網址缺少合約 id"));
      return;
    }
    view.innerHTML = '<div id="cd-body"><div class="placeholder">載入中…</div></div>';
    var body = document.getElementById("cd-body");
    Promise.all([
      api.contractDetail(id, year),
      // 告警是既有端點,單獨失敗不該讓整頁掛掉
      api.contractRisks(year + "-01", 12).catch(function () { return null; }),
    ]).then(function (r) {
      renderContractDetailBody(body, r[0], r[1]);
    }).catch(function (err) { body.innerHTML = errbox("合約詳情", err); });
  }

  function renderContractDetailBody(body, d, risks) {
    crumb.textContent = "綠電合約 › " + d.contract_number;
    var t = d.totals;
    var alerts = risks && risks.alerts
      ? risks.alerts.filter(function (a) { return a.contract_number === d.contract_number; })
      : [];
    var html = '<div class="pagehead"><div><div class="title"><span class="bar"></span>' +
      "<h1>" + esc(d.contract_number) + "</h1>" + contractStatusPill(d.status) + "</div>" +
      '<div class="meta"><span>' + esc(d.wind_farm_name || d.wind_farm_code) + " → " +
      esc(d.company_name) + "</span><span>" + esc(d.start_date) + " ～ " + esc(d.end_date) +
      "</span><span>優先序 " + d.priority + "</span></div>" +
      (contractTerms(d) || "") + "</div>" +
      '<div class="headactions"><a class="btn" href="#/contracts">← 回合約清單</a></div></div>';

    if (!d.has_period_data) {
      html += '<div class="placeholder"><div class="big">📄</div>' +
        "<h2>" + d.year + " 年度尚無發電與用電資料</h2>" +
        "<p>此年度沒有任何量測資料,無法計算履約與金額。以下僅顯示合約條款。</p></div>" +
        contractTermsCard(d);
      body.innerHTML = html;
      return;
    }

    html += '<section class="card"><div class="hd"><h3>全年被什麼卡住</h3>' +
      '<span class="aside">' + d.year + " 年 · 依合約優先序引擎</span></div>" +
      '<div style="padding:14px 18px 4px">' + bindStrip(d.months) +
      '<p class="verdict">' + esc(bindVerdict(d)) + "</p></div>" +
      '<div class="kpis">' +
      kpi("年度分配量", nfmt(t.allocated_mwh, 0) + "<small>MWh</small>",
        "生效 " + t.months_in_force + " 個月", "hl") +
      kpi("上限使用率", t.utilization_percent == null
        ? '<span class="u">未設上限</span>' : pct(t.utilization_percent, 1) + "%",
        t.cap_mwh == null ? "此合約未設上限" : "年度上限 " + nfmt(t.cap_mwh, 0) + " MWh") +
      kpi("保證量差額", t.min_offtake_mwh > 0
        ? nfmt(t.shortfall_mwh, 0) + "<small>MWh</small>" : '<span class="u">無此條款</span>',
        t.min_offtake_mwh > 0
          ? (t.shortfall_months ? t.shortfall_months + " 個月未達標" : "全年皆達標,未觸發")
          : "未約定 take-or-pay",
        t.shortfall_mwh > 0 ? "neg" : "") +
      kpi("風險告警", alerts.length + "<small>則</small>",
        alerts.length ? "見下方清單" : "目前無告警", alerts.length ? "prem" : "") +
      "</div></section>";

    html += contractTermsCard(d);
    body.innerHTML = html;
  }
```

- [ ] **Step 4: 加樣式**

在 `web/styles.css` 尾端追加：

```css
/* ---- 合約詳情：綁定約束分佈條 ---- */
.bstrip{display:flex;gap:4px}
.bcell{flex:1;height:34px;border-radius:6px;display:grid;place-items:center;
  font:600 11px/1 var(--font-mono);color:#fff;border:1px solid transparent}
.b-cap{background:var(--brand)}
.b-sup{background:var(--warn)}
.b-dem{background:var(--buyer)}
.b-non{background:transparent;border:1px dashed var(--line-strong);color:var(--faint)}
.b-nif{background:var(--line-strong);color:var(--muted)}
.blg{display:flex;flex-wrap:wrap;gap:14px;margin-top:9px;font-size:11.5px;color:var(--muted)}
.blg .sw{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:5px;
  vertical-align:-1px}
.verdict{margin:11px 0 2px;font-size:13.5px;line-height:1.65;color:var(--ink)}

/* ---- 合約詳情：月別配比與逐年單價 ---- */
.shbar{display:flex;gap:4px;align-items:flex-end;height:62px}
.shcell{flex:1;display:flex;flex-direction:column;justify-content:flex-end;align-items:center;
  height:100%;gap:3px}
.shcell i{display:block;width:100%;background:var(--seller-soft);border-top:2px solid var(--seller);
  border-radius:3px 3px 0 0}
.shcell b{font:600 10px/1 var(--font-mono);color:var(--faint)}
.pladder{display:flex;flex-wrap:wrap;gap:8px;padding:0 18px 16px}
.pl{display:flex;flex-direction:column;gap:2px;padding:7px 11px;border:1px solid var(--line);
  border-radius:8px;font:600 13px/1.3 var(--font-mono);background:var(--surface-2)}
.pl b{font:600 10.5px/1 var(--font-ui);color:var(--faint)}
```

- [ ] **Step 5: 語法檢查與手動驗證**

```bash
node --check web/app.js && node --check web/api.js
.venv/bin/uvicorn app.main:app --port 8000 &
```

瀏覽 `http://localhost:8000/app/#/contracts`，點任一列，確認：
- 跳到 `#/contract?id=N&year=2024`，麵包屑顯示「綠電合約 › PPA-…」
- 側欄「綠電合約」仍高亮
- 12 格分佈條有顏色、結論句是完整句子
- 「回合約清單」可回去
- PPA-2025-008 的分佈條全灰、條款區的月別配比仍有 12 根柱
- Console 無錯誤

- [ ] **Step 6: 跑閘門**

```bash
.venv/bin/ruff check app tests && .venv/bin/black --check app tests && .venv/bin/mypy app && .venv/bin/pytest -q && node --check web/app.js && node --check web/api.js
```
Expected: 全綠（`tests/integration/test_spa.py` 若有檢查路由清單需一併更新）

- [ ] **Step 7: Commit**

```bash
git add web/app.js web/styles.css
git commit -m "$(cat <<'EOF'
feat(web): make contract rows open a detail page

The list could only ever say what the paper says. Clicking a row now opens
#/contract?id=&year= with the year's binding-constraint distribution and the
contract's terms.

The verdict sentence is assembled from conditions, not adjectives. It only
claims upsell headroom when the API reports months where the farm had spare
energy and the customer unmet demand; it only cites utilisation when a cap
exists; it only mentions being outranked when a higher-priority contract
actually shares the farm. Each clause corresponds to a case the sample data
contains where the unguarded sentence would be false.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: 月別履約圖與單月展開

**Files:**
- Modify: `web/app.js`（`renderContractDetailBody` 內、`contractTermsCard(d)` 之前插入 ② 區）
- Modify: `web/styles.css`

**Interfaces:**
- Consumes: `BIND_META` / `bindMeta()`（Task 5）、`erow` / `erowTotal` / `money` / `nfmt` / `pct`
- Produces:
  - `monthChart(months) -> string`
  - `monthDetailPanel(month, detail) -> string`
  - `wireContractChart(root, detail)`（掛點擊事件）

- [ ] **Step 1: 寫圖表與明細面板**

在 `web/app.js` 的 `contractTermsCard()` 之前插入：

```js
  // 月別履約圖：柱 = 實際分配（依綁定約束上色）,短橫 = 月上限,虛線短橫 = 保證量門檻。
  // 上限用「每月一段短橫」而不是一條連續折線——未設上限的月份沒有值,連起來會憑空
  // 補出一段不存在的線。
  function monthChart(months) {
    var W = 760, Ht = 210, L = 46, R = 12, T = 14, B = 26;
    var pw = W - L - R, ph = Ht - T - B;
    var vals = [1];
    months.forEach(function (m) {
      vals.push(m.allocated_mwh);
      if (m.cap_mwh != null) vals.push(m.cap_mwh);
      if (m.min_offtake_mwh) vals.push(m.min_offtake_mwh);
    });
    var ymax = Math.max.apply(null, vals) * 1.12;
    var bw = pw / 12 * 0.6;
    var X = function (i) { return L + pw * (i + 0.5) / 12; };
    var Y = function (v) { return T + ph - v / ymax * ph; };
    var grid = "", g;
    for (g = 0; g <= 2; g++) {
      var gy = T + ph - ph * g / 2;
      grid += '<line class="cfe-axis" x1="' + L + '" y1="' + gy.toFixed(1) +
        '" x2="' + (W - R) + '" y2="' + gy.toFixed(1) + '"/>' +
        '<text class="mtick" x="' + (L - 6) + '" y="' + (gy + 3.5).toFixed(1) +
        '" text-anchor="end">' + abbr(ymax * g / 2) + "</text>";
    }
    var body = months.map(function (m, i) {
      var meta = bindMeta(m.binding_primary);
      var y = Y(m.allocated_mwh);
      var s = '<rect class="mbar ' + meta.cls + '" data-m="' + m.month + '" x="' +
        (X(i) - bw / 2).toFixed(1) + '" y="' + y.toFixed(1) + '" width="' + bw.toFixed(1) +
        '" height="' + Math.max(0, T + ph - y).toFixed(1) + '" rx="2"><title>' +
        esc(m.period + " · " + meta.name + " · " + nfmt(m.allocated_mwh, 0) + " MWh") +
        "</title></rect>";
      if (m.cap_mwh != null) {
        s += '<line class="mcap" x1="' + (X(i) - bw / 2 - 3).toFixed(1) + '" y1="' +
          Y(m.cap_mwh).toFixed(1) + '" x2="' + (X(i) + bw / 2 + 3).toFixed(1) +
          '" y2="' + Y(m.cap_mwh).toFixed(1) + '"/>';
      }
      if (m.min_offtake_mwh) {
        s += '<line class="mfloor" x1="' + (X(i) - bw / 2 - 3).toFixed(1) + '" y1="' +
          Y(m.min_offtake_mwh).toFixed(1) + '" x2="' + (X(i) + bw / 2 + 3).toFixed(1) +
          '" y2="' + Y(m.min_offtake_mwh).toFixed(1) + '"/>';
      }
      s += '<text class="mtick" x="' + X(i).toFixed(1) + '" y="' + (T + ph + 15) +
        '" text-anchor="middle">' + m.month + "</text>";
      return s;
    }).join("");
    return '<div class="mchart"><svg viewBox="0 0 ' + W + " " + Ht +
      '" role="img" aria-label="月別履約圖">' + grid + body + "</svg></div>" +
      '<div class="blg"><span><i class="ln mcapln"></i>月上限</span>' +
      '<span><i class="ln mfloorln"></i>保證量門檻</span>' +
      '<span class="cfe-hint">點任一柱看該月明細</span></div>';
  }

  // 單月明細。金額只在合約有售電價時才出現。
  function monthDetailPanel(m, d) {
    var rows = erow("狀態", m.in_force ? "生效"
      : '<span class="u">' + esc(m.skip_reason || "未生效") + "</span>");
    rows += erow("分配量", nfmt(m.allocated_mwh, 1), "MWh");
    rows += erow("月上限", m.cap_mwh == null
      ? '<span class="u">未設上限</span>' : nfmt(m.cap_mwh, 1), m.cap_mwh == null ? "" : "MWh");
    rows += erow("使用率", m.utilization_percent == null
      ? '<span class="u">–</span>' : pct(m.utilization_percent, 1) + "%");
    rows += erow("綁定約束", esc(bindMeta(m.binding_primary).name) +
      (m.headroom ? '<span class="u">有加購空間</span>' : ""));
    if (m.min_offtake_mwh) {
      rows += erow("保證量門檻", nfmt(m.min_offtake_mwh, 1), "MWh");
      rows += erow("保證量差額", nfmt(m.shortfall_mwh, 1), "MWh",
        m.shortfall_mwh > 0 ? "neg" : "");
    }
    if (d.has_price) {
      rows += erow("綠電費", money(m.energy_cost), "NTD");
      rows += erow("輪供費", "+" + money(m.wheeling_fee), "NTD");
      if (m.take_or_pay_charge > 0) {
        rows += erow("保證量費", "+" + money(m.take_or_pay_charge), "NTD", "prem");
      }
      rows += erowTotal("買方應付", money(m.buyer_payable), "NTD", "pos");
      rows += erow("案場應收", money(m.seller_receivable), "NTD");
      rows += erow("售電業毛利", money(m.retailer_margin), "NTD",
        m.retailer_margin >= 0 ? "pos" : "neg");
    }
    return '<div class="mdetail"><div class="mdhd"><b>' + esc(m.period) + "</b>" +
      '<span class="aside">' + esc(m.reason || m.skip_reason || "") + "</span></div>" +
      '<div class="rows">' + rows + "</div></div>";
  }

  function wireContractChart(root, d) {
    var panel = root.querySelector("#cd-mdetail");
    if (!panel) return;
    root.addEventListener("click", function (e) {
      var bar = e.target.closest ? e.target.closest(".mbar") : null;
      if (!bar) return;
      var mo = parseInt(bar.getAttribute("data-m"), 10);
      Array.prototype.forEach.call(root.querySelectorAll(".mbar"), function (b) {
        b.classList.toggle("on", b === bar);
      });
      var m = d.months.filter(function (x) { return x.month === mo; })[0];
      if (m) panel.innerHTML = monthDetailPanel(m, d);
    });
  }
```

- [ ] **Step 2: 把 ② 區接進頁面**

在 `renderContractDetailBody` 內，`html += contractTermsCard(d);` **之前**插入：

```js
    html += '<section class="card"><div class="hd"><h3>月別履約</h3>' +
      '<span class="aside">柱＝實際分配 · 短橫＝月上限</span></div>' +
      '<div style="padding:12px 18px 14px">' + monthChart(d.months) + "</div>" +
      '<div id="cd-mdetail"></div></section>';
```

並把函式結尾的

```js
    body.innerHTML = html;
```

改為

```js
    body.innerHTML = html;
    wireContractChart(body, d);
```

（`has_period_data` 為 false 的早退分支不呼叫 `wireContractChart`，維持原樣。）

- [ ] **Step 3: 加樣式**

在 `web/styles.css` 尾端追加：

```css
/* ---- 合約詳情：月別履約圖 ---- */
.mchart svg{width:100%;height:auto;display:block}
.mbar{cursor:pointer;transition:opacity .12s}
.mbar:hover{opacity:.82}
.mbar.on{stroke:var(--ink);stroke-width:1.5}
.mbar.b-cap{fill:var(--brand)} .mbar.b-sup{fill:var(--warn)}
.mbar.b-dem{fill:var(--buyer)} .mbar.b-nif{fill:var(--line-strong)}
.mbar.b-non{fill:none;stroke:var(--line-strong);stroke-dasharray:3 3}
.mcap{stroke:var(--ink);stroke-width:2}
.mfloor{stroke:var(--warn);stroke-width:1.6;stroke-dasharray:4 3}
.mtick{font:500 10px var(--font-mono);fill:var(--faint)}
.blg .ln{display:inline-block;width:14px;height:0;border-top:2px solid var(--ink);
  margin-right:5px;vertical-align:3px}
.blg .mfloorln{border-top:2px dashed var(--warn)}
.mdetail{border-top:1px solid var(--line);padding:12px 18px 16px}
.mdhd{display:flex;align-items:baseline;gap:10px;margin-bottom:4px;font-size:14px}
.mdhd .aside{margin-left:auto;font:500 11px var(--font-mono);color:var(--faint)}
```

- [ ] **Step 4: 手動驗證**

`node --check web/app.js`，重新載入 `#/contract?id=5&year=2024`：
- 12 根柱高度一致（PPA-2022-005 每月都是 1250），上限短橫貼齊柱頂
- 點任一柱 → 下方出現該月明細，含引擎英文原文 reason
- 換到 PPA-2024-004 → 柱是橘色且明顯低於上限短橫
- Console 無錯誤

- [ ] **Step 5: 跑閘門**

```bash
.venv/bin/pytest -q && node --check web/app.js
```
Expected: 全綠

- [ ] **Step 6: Commit**

```bash
git add web/app.js web/styles.css
git commit -m "$(cat <<'EOF'
feat(web): chart the contract's twelve months and drill into one

Bars are the allocation, coloured by binding constraint; a short rule marks
the month's cap and a dashed one the take-or-pay floor. Clicking a bar opens
that month, including the engine's own reason string so the number can be
audited rather than trusted.

The cap is drawn as a tick per month rather than a connected line: months
with no cap have no value, and joining across them would draw a limit that
does not exist.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: 風險告警與雙面帳

**Files:**
- Modify: `web/app.js`（`renderContractDetailBody` 內、`contractTermsCard(d)` 之前）
- Modify: `web/styles.css`

**Interfaces:**
- Consumes: `sevPill()`（`:749`）、`RISK_CAT`（`:748`）、`money()`、`erow`/`erowTotal`、`iconInfo()`
- Produces:
  - `alertsBlock(alerts, year) -> string`
  - `billBlock(detail) -> string`

- [ ] **Step 1: 寫兩個區塊**

在 `web/app.js` 的 `contractTermsCard()` 之前插入：

```js
  function alertsBlock(alerts, year) {
    var rows = "";
    if (!alerts.length) {
      rows = '<tr><td class="empty" colspan="4">目前無風險告警 ✓</td></tr>';
    } else {
      alerts.forEach(function (a) {
        rows += "<tr><td>" + sevPill(a.severity) + "</td><td>" +
          (RISK_CAT[a.category] || esc(a.category)) +
          '</td><td style="text-align:left">' + esc(a.detail) +
          '</td><td style="text-align:left">' + esc(a.suggested_action) + "</td></tr>";
      });
    }
    return '<section class="card"><div class="hd"><h3>風險告警</h3>' +
      '<span class="aside">評估期間 ' + year + "-01 · 到期預警 12 個月</span></div>" +
      '<div class="tablewrap"><table><thead><tr><th>嚴重度</th><th>類型</th>' +
      "<th>說明</th><th>建議動作</th></tr></thead><tbody>" + rows +
      "</tbody></table></div></section>";
  }

  // 雙面帳：買方帳、賣方帳、售電業毛利同框,並標明每一欄是給誰看的。
  function billBlock(d) {
    if (!d.has_price) {
      return '<section class="card"><div class="hd"><h3>雙面帳</h3></div>' +
        '<div style="padding:16px 18px"><p class="u">本合約未設售電價,無法計算金額。' +
        "填入售電價後即可產生買方應付、案場應收與售電業毛利。</p></div></section>";
    }
    var t = d.totals;
    var rows = "";
    d.months.forEach(function (m) {
      rows += "<tr" + (m.in_force ? "" : ' class="dim"') + '><td class="num">' +
        esc(m.period) + '</td><td class="num">' + nfmt(m.allocated_mwh, 0) +
        '</td><td class="num">' + money(m.energy_cost) +
        '</td><td class="num">' + money(m.wheeling_fee) +
        '</td><td class="num">' + (m.take_or_pay_charge > 0
          ? '<span class="prem">' + money(m.take_or_pay_charge) + "</span>" : "0") +
        '</td><td class="num">' + money(m.buyer_payable) +
        '</td><td class="num">' + money(m.seller_receivable) +
        '</td><td class="num ' + (m.retailer_margin >= 0 ? "pos" : "neg") + '">' +
        money(m.retailer_margin) + "</td></tr>";
    });
    return '<section class="card"><div class="hd"><h3>雙面帳</h3>' +
      '<span class="aside">' + d.year + " 年度合計 · 履約基準</span></div>" +
      '<div class="billcols">' +
      '<div class="billcol"><div class="bctag buyer">買方（用電戶應付）</div><div class="rows">' +
      erow("綠電費", money(t.energy_cost), "NTD") +
      erow("輪供費", "+" + money(t.wheeling_fee), "NTD") +
      (t.take_or_pay_charge > 0
        ? erow("保證量費", "+" + money(t.take_or_pay_charge), "NTD", "prem") : "") +
      erowTotal("應付合計", money(t.buyer_payable), "NTD", "pos") +
      "</div></div>" +
      '<div class="billcol"><div class="bctag seller">賣方（案場應收）</div><div class="rows">' +
      erow("躉售單價", price(d.feed_in_price_per_kwh), "NTD/kWh") +
      erow("綠電量", nfmt(t.allocated_mwh, 0), "MWh") +
      erowTotal("應收合計", money(t.seller_receivable), "NTD") +
      "</div></div>" +
      '<div class="billcol"><div class="bctag">售電業毛利</div><div class="rows">' +
      erow("轉供單價", price(d.months[0].price_per_kwh), "NTD/kWh") +
      erow("毛利率", t.margin_percent == null
        ? '<span class="u">–</span>' : pct(t.margin_percent, 1) + "%") +
      erowTotal("毛利", money(t.retailer_margin), "NTD",
        t.retailer_margin >= 0 ? "pos" : "neg") +
      "</div></div></div>" +
      '<div class="subhd"><span>月別明細</span><small>灰列為未生效月份</small></div>' +
      '<div class="tablewrap"><table><thead><tr><th>期間</th><th>分配 (MWh)</th>' +
      "<th>綠電費</th><th>輪供費</th><th>保證量費</th><th>買方應付</th>" +
      "<th>案場應收</th><th>毛利</th></tr></thead><tbody>" + rows +
      "</tbody></table></div>" +
      '<div class="foot-note">' + iconInfo() +
      "本頁金額以<b>合約優先序引擎</b>的分配為基準(履約基準);轉供結算單頁採 MILP 最佳化配置," +
      "兩者數字會有落差。" +
      (d.used_default_feed_in
        ? "此案場未設躉售價,採預設 " + price(d.feed_in_price_per_kwh) + " 元/度 試算。" : "") +
      "輪供費 " + price(d.wheeling_fee_per_kwh) + " 元/度。減碳量 " +
      nfmt(t.carbon_avoided_tco2e, 0) + " tCO₂e。</div>" +
      "</section>";
  }
```

- [ ] **Step 2: 接進頁面**

在 `renderContractDetailBody` 內，`html += contractTermsCard(d);` **之前**插入：

```js
    html += alertsBlock(alerts, d.year);
    html += billBlock(d);
```

- [ ] **Step 3: 加樣式**

在 `web/styles.css` 尾端追加：

```css
/* ---- 合約詳情：雙面帳 ---- */
.billcols{display:grid;grid-template-columns:repeat(3,1fr);gap:0;
  border-bottom:1px solid var(--line)}
.billcol{padding:14px 18px 16px;border-right:1px solid var(--line)}
.billcol:last-child{border-right:0}
.billcol .rows{margin-top:6px}
.bctag{display:inline-block;font-size:11px;font-weight:650;padding:3px 9px;border-radius:20px;
  background:var(--surface-2);color:var(--muted);border:1px solid var(--line)}
.bctag.buyer{background:var(--buyer-soft);color:var(--buyer);border-color:transparent}
.bctag.seller{background:var(--seller-soft);color:var(--seller);border-color:transparent}
tbody tr.dim td{opacity:.45}
@media (max-width:900px){.billcols{grid-template-columns:1fr}
  .billcol{border-right:0;border-bottom:1px solid var(--line)}}
```

- [ ] **Step 4: 手動驗證**

`node --check web/app.js`，重新載入詳情頁：
- 雙面帳三欄，買方青綠標籤、賣方靛藍標籤
- 月別明細表 12 列，未生效月份呈灰
- 底部註記完整（履約基準說明 + 輪供費 + 減碳量）
- PPA-2024-004 的告警區有「供電不足」告警
- Console 無錯誤

- [ ] **Step 5: 跑閘門**

```bash
.venv/bin/pytest -q && node --check web/app.js
```
Expected: 全綠

- [ ] **Step 6: Commit**

```bash
git add web/app.js web/styles.css
git commit -m "$(cat <<'EOF'
feat(web): add the alerts and two-sided bill to the contract page

Three columns — buyer payable, farm receivable, retailer margin — each
labelled with whose side it is, plus a twelve-row monthly breakdown with
out-of-force months dimmed rather than hidden.

The footer states outright that these figures come from the priority engine
and will not tie out against the settlement page, which optimises. It also
names the wheeling rate and, when the farm has no tariff on file, says the
cost side is a default assumption. Showing a retailer a margin without
saying where the cost came from is how a demo turns into a dispute.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: 瀏覽器驗收、名詞說明與 CHANGELOG

**Files:**
- Modify: `web/app.js`（`INFO` 物件 `:1843-1915`，加一則說明）
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: 前七個 task 的全部產出
- Produces: `INFO.bindingConstraint` 說明卡

- [ ] **Step 1: 加名詞說明**

在 `web/app.js` 的 `INFO` 物件內、`storage` 之後加：

```js
    bindingConstraint: {
      title: "綁定約束（這個月被什麼卡住）",
      html:
        "<p>每個月的分配量都是三個上限取最小：<b>案場當月還剩多少電</b>、<b>客戶還有多少沒被綠電覆蓋的用電</b>、<b>合約自己的上限</b>。實際卡住的那一個,就是這個月的綁定約束。</p>" +
        "<p><b>合約上限</b>——客戶要得比合約允許的多。若案場同時還有餘電,就代表<b>有加購空間</b>。<br>" +
        "<b>案場供給</b>——案場的電被分光了。這時調高合約上限也拿不到更多,要看的是案場是否超賣、或本合約優先序是否排在後面。<br>" +
        "<b>客戶用電</b>——合約允許量高於客戶用得掉的量,多簽的部分是浪費;若合約帶 take-or-pay,還會產生保證量費。</p>" +
        '<p class="tip-eg">同時卡在兩個約束時,顯示較硬的那一個（案場供給 &gt; 客戶用電 &gt; 合約上限）。</p>',
    },
```

在 `renderContractDetailBody` 的 ① 區標題加上 ⓘ：把

```js
    html += '<section class="card"><div class="hd"><h3>全年被什麼卡住</h3>' +
```

改為

```js
    html += '<section class="card"><div class="hd"><h3>全年被什麼卡住' +
      infoTip("bindingConstraint") + "</h3>" +
```

- [ ] **Step 2: Playwright 驗收三紙合約**

先確認 `.venv/bin/uvicorn app.main:app --port 8000` 已在跑。將以下存成暫存檔（例如 `/tmp/verify_contract_detail.js`）並用本機既有的 Playwright 執行：

```js
const { chromium } = require("playwright");
(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = [];
  page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
  page.on("pageerror", (e) => errors.push(String(e)));

  const cases = [
    ["PPA-2022-005", "cap"],
    ["PPA-2024-004", "supply"],
    ["PPA-2025-008", "notinforce"],
  ];
  await page.goto("http://localhost:8000/app/#/contracts", { waitUntil: "networkidle" });
  const ids = await page.evaluate(async () => {
    const r = await fetch("/api/v1/contracts?limit=1000").then((x) => x.json());
    const m = {};
    r.forEach((c) => { m[c.contract_number] = c.id; });
    return m;
  });

  for (const [num, tag] of cases) {
    await page.goto(`http://localhost:8000/app/#/contract?id=${ids[num]}&year=2024`,
      { waitUntil: "networkidle" });
    await page.waitForTimeout(600);
    const info = await page.evaluate(() => {
      const wrap = document.querySelector(".tablewrap");
      const tbl = wrap && wrap.querySelector("table");
      return {
        cells: document.querySelectorAll(".bcell").length,
        verdict: (document.querySelector(".verdict") || {}).textContent || "",
        bars: document.querySelectorAll(".mbar").length,
        bill: !!document.querySelector(".billcols"),
        terms: document.querySelectorAll(".shcell").length,
        overflow: tbl ? tbl.scrollWidth - wrap.clientWidth : 0,
      };
    });
    console.log(num, JSON.stringify(info));
    await page.screenshot({ path: `/tmp/cd-${tag}.png`, fullPage: true });
  }
  console.log("console errors:", errors.length, errors.slice(0, 5));
  await browser.close();
})();
```

驗收標準：
- 三紙皆 `cells === 12`
- `verdict` 是完整中文句子且**不含** `undefined` / `NaN` / `null`
- PPA-2022-005 與 PPA-2024-004：`bars === 12`、`bill === true`
- PPA-2025-008：`terms === 12`（未生效也看得到月別配比）
- 每一紙 `overflow <= 0`（表格不溢出 wrapper——這個專案先前在合約清單上栽過一次）
- `console errors: 0`

任何一項不過就修到過，不要略過。

- [ ] **Step 3: 更新 CHANGELOG**

在 `CHANGELOG.md` 的 `## [Unreleased]` 底下（沒有就在最上方新增一節）加：

```markdown
### Added
- **合約詳情頁（商務視角）** — 合約清單每一列可點入 `#/contract?id=&year=`，看該紙合約整年的逐月履約與雙面帳。
  - **全年被什麼卡住**：12 格分佈條標出每個月的綁定約束（合約上限／案場供給／客戶用電／未生效），並產生一句有成立條件的結論——「有加購空間」只在案場尚有餘電且客戶仍有未滿足用電時才會出現。
  - **月別履約圖**：柱為實際分配、短橫為月上限、虛線短橫為 take-or-pay 門檻；點任一月展開明細，含引擎原文的分配理由。
  - **雙面帳**：買方應付、案場應收、售電業毛利同頁分欄，公式沿用轉供結算單，並註明本頁為履約基準（合約優先序引擎）、與結算單的最佳化基準會有落差。
  - 新增唯讀端點 `GET /api/v1/analytics/contract-detail?contract_id=&year=`。
  - 未設售電價的合約不顯示金額而非以躉售價代入；未設上限的合約使用率顯示「未設上限」而非 0%。
```

- [ ] **Step 4: 跑完整閘門**

```bash
.venv/bin/ruff check app tests && .venv/bin/black --check app tests && .venv/bin/mypy app && .venv/bin/pytest -q && node --check web/app.js && node --check web/api.js
```
Expected: 全綠

- [ ] **Step 5: Commit**

```bash
git add web/app.js CHANGELOG.md
git commit -m "$(cat <<'EOF'
docs(contracts): explain the binding constraint and log the detail page

Adds the ⓘ card behind the year-at-a-glance heading. A retailer reading
"limited by farm supply" needs to know that raising the cap would not help —
that is the whole commercial point of the distinction, and it is not obvious
from the label alone.

Verified in the browser across the three shapes the sample data produces:
cap-bound (PPA-2022-005), supply-bound (PPA-2024-004), and never in force
during the year (PPA-2025-008, which still renders its monthly-share curve
because the clause is data whether or not it ran).

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review

**Spec 覆蓋**

| Spec 章節 | Task |
|---|---|
| §3 引擎選擇與差異揭露 | 3（公式）、7（頁面註記） |
| §4 架構與資料流 | 2 |
| §5 綁定約束分類、優先序、結論句、headroom | 1、2、5 |
| §6 金額公式、三個不能假裝有值的欄位 | 3 |
| §7 Schema | 2 |
| §8 端點 | 4 |
| §9 路由與五個版面區塊 | 5、6、7 |
| §10 錯誤處理六種情境 | 2（未生效、無資料、未設上限）、3（未設售電價、未設躉售價）、5（404） |
| §11 測試 | 1–4（Python）、8（Playwright） |
| §12 Gate | 每個 task 的閘門步驟 |
| §13 不在範圍內 | 未實作，符合 |

**型別一致性**：`classify_binding` 在 Task 1 定義、Task 2 使用；`has_headroom` 同。`_build_months` / `_build_totals` 的簽章在 Task 3 擴充（多一個 `pricing` / `has_price` 參數），Task 3 已明寫改法。`BIND_META` / `bindMeta()` 在 Task 5 定義、Task 6 使用。`sevPill` / `RISK_CAT` 為既有函式（`web/app.js:748-749`）。

**已知順序相依**：Task 6 與 7 都在 `renderContractDetailBody` 的 `contractTermsCard(d)` 之前插入區塊，兩者順序為 ②（Task 6）在前、③④（Task 7）在後。若 Task 7 先做，插入點改為 `monthChart` 區塊之後即可。
