# P3 經濟最佳化媒合 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增一個以 MILP(PuLP+CBC)求解、目標為售電毛利最大、RE 為硬約束(不可行退軟)、支援「最少案場數 / 最小分配%」結構約束的**全域最佳化媒合模式**,與既有優先序引擎並存。

**Architecture:** 新純函式模組 `app/matching/optimizer.py`(不動 `match_period`);既有輸入 dataclass 加可選欄位帶入價格/RE 目標;`optimize_service.compute_optimized` 從 DB 建輸入、求解、回 schema(不落地);`GET /api/v1/matching/optimize` 端點 + 儀表板頁並列對比兩種策略。

**Tech Stack:** Python 3.12 · PuLP(內建 CBC) · FastAPI · SQLAlchemy 2 · Pydantic 2 · Streamlit · pytest。

## Global Constraints

- 語言:所有面向使用者字串與文件用**繁體中文(zh-TW)**;程式碼識別字用英文。
- `app/matching/engine.py::match_period` 的**行為不得改變**;既有測試須全綠(僅允許加可選 dataclass 欄位、抽出等價的 summary helper)。
- optimizer 為**純函式、無 I/O、deterministic**:`PULP_CBC_CMD(msg=0, threads=1)`,同輸入(含打亂順序)須得完全相同分配(四捨五入 6 位後比較)。
- compute-only:**不新增資料表、不落地**(比照 `app/services/evaluation.py`)。
- 懲罰常數(模組級,固定值):`_KWH=1000.0`、`_P_RE=1e6`、`_P_SITE=1e3`、`_EPSILON=1e-6`;毛利項正規化到 [−1,1] 後再套用(見 Task 3)。
- 度數 = MWh × 1000;金額單位 NTD。
- 最小分配% 定義為「佔**該客戶用電量**的百分比」。
- 分配值一律 `round(..., 6)`;RE 達標判定容差 `_EPS=1e-9`。
- 預設 `optimize_min_sites_per_customer=0`、`optimize_min_site_allocation_percent=0.0`(關閉時不改變任何既有行為)。

---

### Task 1: 相依與設定(pulp + 最佳化預設值)

**Files:**
- Modify: `pyproject.toml:9-20`(dependencies 加 `pulp`)
- Modify: `app/core/config.py:30-32`(加兩個設定)
- Test: `tests/unit/test_config_economics.py`(既有檔,加測項)

**Interfaces:**
- Produces: `settings.optimize_min_sites_per_customer: int`(預設 0)、`settings.optimize_min_site_allocation_percent: float`(預設 0.0);環境可用 `pulp`。

- [ ] **Step 1: 寫失敗測試**

在 `tests/unit/test_config_economics.py` 末尾加:

```python
def test_optimization_defaults_present():
    from app.core.config import Settings

    s = Settings()
    assert s.optimize_min_sites_per_customer == 0
    assert s.optimize_min_site_allocation_percent == 0.0


def test_pulp_importable_with_cbc():
    import pulp

    solver = pulp.PULP_CBC_CMD(msg=0, threads=1)
    assert solver.available()
```

- [ ] **Step 2: 執行驗證失敗**

Run: `.venv/bin/python -m pytest tests/unit/test_config_economics.py -q`
Expected: FAIL(`AttributeError: ... optimize_min_sites_per_customer` 或 `ModuleNotFoundError: pulp`)

- [ ] **Step 3: 加相依**

在 `pyproject.toml` 的 `dependencies` list 內(`httpx>=0.27",` 之後、`]` 之前)加一行:

```toml
    # P3 economic optimizer: MILP via PuLP (bundles the CBC solver binary).
    "pulp>=2.8",
```

- [ ] **Step 4: 安裝相依**

Run: `.venv/bin/python -m pip install -e ".[dashboard,dev]"`
Expected: 成功安裝 `pulp`。

- [ ] **Step 5: 加設定**

在 `app/core/config.py` 的 `default_feed_in_price_per_kwh: float = 4.0` 之後加:

```python

    # Economic optimizer (P3) — structural constraints, off by default
    optimize_min_sites_per_customer: int = 0
    optimize_min_site_allocation_percent: float = 0.0
```

- [ ] **Step 6: 執行驗證通過**

Run: `.venv/bin/python -m pytest tests/unit/test_config_economics.py -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml app/core/config.py tests/unit/test_config_economics.py
git commit -m "feat(p3): add pulp dependency and optimizer config defaults"
```

---

### Task 2: 輸入 dataclass 加可選欄位 + 抽出 summary helper

**Files:**
- Modify: `app/matching/engine.py`(`FarmSupply` / `ContractInput` / `CustomerDemand` 加欄位;加兩個 summary helper 並改 `match_period` 尾段呼叫它們)
- Modify: `app/matching/__init__.py`(匯出新 helper)
- Test: `tests/unit/test_matching_engine.py`(既有檔,加向後相容測項)

**Interfaces:**
- Produces:
  - `FarmSupply(farm_id, generated_mwh, feed_in_price_per_kwh: float | None = None)`
  - `ContractInput(..., price_per_kwh: float | None = None)`(接在既有欄位之後)
  - `CustomerDemand(customer_id, consumed_mwh, green_target_type: str | None = None, re_target_percent: float | None = None, target_energy_mwh: float | None = None)`
  - `build_customer_summary(customer_id: int, consumption_mwh: float, allocated_mwh: float) -> CustomerSummary`
  - `build_farm_summary(farm_id: int, generated_mwh: float, allocated_mwh: float) -> FarmSummary`

- [ ] **Step 1: 寫失敗測試**

在 `tests/unit/test_matching_engine.py` 末尾加:

```python
def test_optional_fields_default_none_and_ignored_by_engine():
    from datetime import date

    from app.matching.engine import (
        ContractInput,
        CustomerDemand,
        FarmSupply,
        match_period,
    )

    farms = [FarmSupply(farm_id=1, generated_mwh=100.0, feed_in_price_per_kwh=4.0)]
    demands = [
        CustomerDemand(
            customer_id=1,
            consumed_mwh=100.0,
            green_target_type="re_percent",
            re_target_percent=50.0,
            target_energy_mwh=None,
        )
    ]
    contracts = [
        ContractInput(
            contract_id=1,
            contract_number="C1",
            wind_farm_id=1,
            customer_id=1,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
            status="active",
            priority=100,
            contracted_energy_mwh=None,
            contracted_percentage=None,
            price_per_kwh=4.5,
        )
    ]
    out = match_period("2024-01", date(2024, 1, 1), date(2024, 1, 31), farms, demands, contracts)
    # engine ignores the new fields; full allocation as before
    assert out.allocations[0].allocated_mwh == 100.0


def test_summary_helpers_match_inline_math():
    from app.matching.engine import build_customer_summary, build_farm_summary

    cs = build_customer_summary(1, 100.0, 55.5555555)
    assert cs.allocated_mwh == 55.555556
    assert cs.achieved_re_percent == 55.555556
    cs0 = build_customer_summary(2, 0.0, 0.0)
    assert cs0.achieved_re_percent == 0.0
    fs = build_farm_summary(1, 100.0, 40.0)
    assert fs.unallocated_mwh == 60.0
```

- [ ] **Step 2: 執行驗證失敗**

Run: `.venv/bin/python -m pytest tests/unit/test_matching_engine.py -q`
Expected: FAIL(`TypeError: ... unexpected keyword argument 'feed_in_price_per_kwh'` 或 `ImportError: build_customer_summary`)

- [ ] **Step 3: 加 dataclass 欄位**

`app/matching/engine.py` 中 `FarmSupply` 改為:

```python
@dataclass(frozen=True)
class FarmSupply:
    farm_id: int
    generated_mwh: float
    feed_in_price_per_kwh: float | None = None
```

`ContractInput` 在 `contracted_percentage` 之後加一行:

```python
    contracted_percentage: float | None = None
    price_per_kwh: float | None = None
```

`CustomerDemand` 改為:

```python
@dataclass(frozen=True)
class CustomerDemand:
    customer_id: int
    consumed_mwh: float
    green_target_type: str | None = None
    re_target_percent: float | None = None
    target_energy_mwh: float | None = None
```

- [ ] **Step 4: 加 summary helper 並改 match_period 尾段呼叫**

在 `app/matching/engine.py` 的 `match_period` 定義**之前**(緊接 `_reason` 函式之後)加:

```python
def build_customer_summary(
    customer_id: int, consumption_mwh: float, allocated_mwh: float
) -> CustomerSummary:
    """Per-customer allocation summary (shared by the engine and the optimizer)."""
    allocated = round(allocated_mwh, 6)
    achieved = (
        round(allocated / consumption_mwh * 100.0, 6) if consumption_mwh > 0 else 0.0
    )
    return CustomerSummary(customer_id, consumption_mwh, allocated, achieved)


def build_farm_summary(
    farm_id: int, generated_mwh: float, allocated_mwh: float
) -> FarmSummary:
    """Per-farm allocation summary (shared by the engine and the optimizer)."""
    allocated = round(allocated_mwh, 6)
    return FarmSummary(
        farm_id=farm_id,
        generated_mwh=generated_mwh,
        allocated_mwh=allocated,
        unallocated_mwh=round(generated_mwh - allocated, 6),
    )
```

把 `match_period` 尾段兩個彙總迴圈改為呼叫 helper:

```python
    for d in demands:
        outcome.customer_summaries.append(
            build_customer_summary(
                d.customer_id,
                d.consumed_mwh,
                allocated_to_customer.get(d.customer_id, 0.0),
            )
        )

    for f in farms:
        outcome.farm_summaries.append(
            build_farm_summary(
                f.farm_id,
                f.generated_mwh,
                allocated_to_farm.get(f.farm_id, 0.0),
            )
        )

    return outcome
```

- [ ] **Step 5: 匯出 helper**

`app/matching/__init__.py` 的 import 與 `__all__` 加入 `build_customer_summary`、`build_farm_summary`:

```python
from app.matching.engine import (
    Allocation,
    ContractInput,
    CustomerDemand,
    CustomerSummary,
    FarmSummary,
    FarmSupply,
    MatchingOutcome,
    SkippedContract,
    build_customer_summary,
    build_farm_summary,
    match_period,
)

__all__ = [
    "Allocation",
    "ContractInput",
    "CustomerDemand",
    "CustomerSummary",
    "FarmSummary",
    "FarmSupply",
    "MatchingOutcome",
    "SkippedContract",
    "build_customer_summary",
    "build_farm_summary",
    "match_period",
]
```

- [ ] **Step 6: 執行驗證通過(含既有引擎測試回歸)**

Run: `.venv/bin/python -m pytest tests/unit/test_matching_engine.py -q`
Expected: PASS(新測 + 所有既有引擎測試皆綠)

- [ ] **Step 7: Commit**

```bash
git add app/matching/engine.py app/matching/__init__.py tests/unit/test_matching_engine.py
git commit -m "feat(p3): extend matching dataclasses with optional fields; extract summary helpers"
```

---

### Task 3: optimizer.py — MILP 全域最佳化(核心)

**Files:**
- Create: `app/matching/optimizer.py`
- Modify: `app/matching/__init__.py`(匯出 optimizer 公開符號)
- Test: `tests/unit/test_optimizer.py`

**Interfaces:**
- Consumes: `FarmSupply` / `CustomerDemand` / `ContractInput`(含 Task 2 新欄位)、`_is_eligible` / `_contract_limit` / `build_customer_summary` / `build_farm_summary` / `MatchingOutcome` / `Allocation` / `SkippedContract`(來自 `app.matching.engine`)。
- Produces:
  - `CustomerTarget`(dataclass)
  - `OptimizationOutcome(MatchingOutcome)`,加 `solver_status: str`、`objective_gross_margin_ntd: float`、`customer_targets: list[CustomerTarget]`
  - `OptimizeOptions`(dataclass):`min_sites_per_customer: int = 0`、`min_site_allocation_percent: float = 0.0`、`default_feed_in_price_per_kwh: float = 4.0`
  - `optimize_period(period: str, period_start: date, period_end: date, farms: list[FarmSupply], demands: list[CustomerDemand], contracts: list[ContractInput], options: OptimizeOptions) -> OptimizationOutcome`

- [ ] **Step 1: 寫失敗測試**

Create `tests/unit/test_optimizer.py`:

```python
"""Unit tests for the MILP economic optimizer."""

from __future__ import annotations

from datetime import date

import pytest

from app.matching.engine import (
    ContractInput,
    CustomerDemand,
    FarmSupply,
    match_period,
)
from app.matching.optimizer import OptimizeOptions, optimize_period

START = date(2024, 1, 1)
END = date(2024, 1, 31)
OPTS = OptimizeOptions(default_feed_in_price_per_kwh=4.0)


def _contract(cid, num, farm, cust, price, energy=None, pct=None, priority=100):
    return ContractInput(
        contract_id=cid,
        contract_number=num,
        wind_farm_id=farm,
        customer_id=cust,
        start_date=START,
        end_date=END,
        status="active",
        priority=priority,
        contracted_energy_mwh=energy,
        contracted_percentage=pct,
        price_per_kwh=price,
    )


def _alloc_map(outcome):
    return {a.contract_id: a.allocated_mwh for a in outcome.allocations}


def test_prefers_higher_margin_farm():
    # Two farms can each fully supply the customer; farm 2's contract has more margin.
    farms = [
        FarmSupply(1, 100.0, feed_in_price_per_kwh=4.0),
        FarmSupply(2, 100.0, feed_in_price_per_kwh=4.0),
    ]
    demands = [CustomerDemand(1, 100.0, green_target_type="re_percent", re_target_percent=0.0)]
    contracts = [
        _contract(1, "C1", 1, 1, price=4.3),  # margin 0.3
        _contract(2, "C2", 2, 1, price=4.9),  # margin 0.9
    ]
    out = optimize_period("2024-01", START, END, farms, demands, contracts, OPTS)
    alloc = _alloc_map(out)
    assert alloc[2] == 100.0
    assert alloc[1] == 0.0
    # gross margin = 100 MWh * 1000 * 0.9 = 90000 NTD
    assert out.objective_gross_margin_ntd == pytest.approx(90000.0, abs=1.0)
    assert out.solver_status == "Optimal"


def test_re_hard_constraint_met_when_feasible():
    farms = [
        FarmSupply(1, 100.0, feed_in_price_per_kwh=4.0),
        FarmSupply(2, 100.0, feed_in_price_per_kwh=4.0),
    ]
    demands = [CustomerDemand(1, 100.0, green_target_type="re_percent", re_target_percent=80.0)]
    # Only the low-margin farm can serve; RE target must still be met.
    contracts = [_contract(1, "C1", 1, 1, price=4.1)]
    out = optimize_period("2024-01", START, END, farms, demands, contracts, OPTS)
    ct = {c.customer_id: c for c in out.customer_targets}[1]
    assert ct.re_target_mwh == 80.0
    assert ct.allocated_mwh >= 80.0 - 1e-6
    assert ct.re_target_met is True
    assert ct.re_shortfall_mwh == 0.0


def test_re_soft_fallback_when_infeasible():
    # Demand 100, target 80, but only 50 MWh of supply exists → shortfall 30.
    farms = [FarmSupply(1, 50.0, feed_in_price_per_kwh=4.0)]
    demands = [CustomerDemand(1, 100.0, green_target_type="re_percent", re_target_percent=80.0)]
    contracts = [_contract(1, "C1", 1, 1, price=4.5)]
    out = optimize_period("2024-01", START, END, farms, demands, contracts, OPTS)
    ct = {c.customer_id: c for c in out.customer_targets}[1]
    assert ct.allocated_mwh == pytest.approx(50.0, abs=1e-6)
    assert ct.re_shortfall_mwh == pytest.approx(30.0, abs=1e-6)
    assert ct.re_target_met is False


def test_energy_target_type():
    farms = [FarmSupply(1, 100.0, feed_in_price_per_kwh=4.0)]
    demands = [CustomerDemand(1, 100.0, green_target_type="energy", target_energy_mwh=25.0)]
    contracts = [_contract(1, "C1", 1, 1, price=4.5)]
    out = optimize_period("2024-01", START, END, farms, demands, contracts, OPTS)
    ct = {c.customer_id: c for c in out.customer_targets}[1]
    assert ct.re_target_mwh == 25.0
    assert ct.allocated_mwh >= 25.0 - 1e-6


def test_min_sites_forces_spread():
    # Customer could be fully served by farm 2 alone (higher margin), but min_sites=2
    # forces using both farms.
    farms = [
        FarmSupply(1, 100.0, feed_in_price_per_kwh=4.0),
        FarmSupply(2, 100.0, feed_in_price_per_kwh=4.0),
    ]
    demands = [CustomerDemand(1, 100.0, green_target_type="re_percent", re_target_percent=100.0)]
    contracts = [
        _contract(1, "C1", 1, 1, price=4.3),
        _contract(2, "C2", 2, 1, price=4.9),
    ]
    opts = OptimizeOptions(min_sites_per_customer=2, default_feed_in_price_per_kwh=4.0)
    out = optimize_period("2024-01", START, END, farms, demands, contracts, opts)
    ct = {c.customer_id: c for c in out.customer_targets}[1]
    assert ct.sites_used == 2
    assert ct.site_shortfall == 0


def test_min_sites_shortfall_when_not_enough_farms():
    farms = [FarmSupply(1, 100.0, feed_in_price_per_kwh=4.0)]
    demands = [CustomerDemand(1, 100.0, green_target_type="re_percent", re_target_percent=100.0)]
    contracts = [_contract(1, "C1", 1, 1, price=4.5)]
    opts = OptimizeOptions(min_sites_per_customer=3, default_feed_in_price_per_kwh=4.0)
    out = optimize_period("2024-01", START, END, farms, demands, contracts, opts)
    ct = {c.customer_id: c for c in out.customer_targets}[1]
    # only 1 eligible contract → min_sites clamped to 1 → no shortfall
    assert ct.sites_used == 1
    assert ct.site_shortfall == 0


def test_min_site_allocation_percent_excludes_slivers():
    # Farm 2 caps at 5 MWh (5% of demand); floor 10% → farm 2 cannot be used.
    farms = [
        FarmSupply(1, 100.0, feed_in_price_per_kwh=4.0),
        FarmSupply(2, 100.0, feed_in_price_per_kwh=4.0),
    ]
    demands = [CustomerDemand(1, 100.0, green_target_type="re_percent", re_target_percent=100.0)]
    contracts = [
        _contract(1, "C1", 1, 1, price=4.3),
        _contract(2, "C2", 2, 1, price=4.9, energy=5.0),  # capped at 5 MWh
    ]
    opts = OptimizeOptions(
        min_site_allocation_percent=10.0, default_feed_in_price_per_kwh=4.0
    )
    out = optimize_period("2024-01", START, END, farms, demands, contracts, opts)
    alloc = _alloc_map(out)
    assert alloc[2] == 0.0  # sliver excluded by the floor
    assert alloc[1] == 100.0


def test_deterministic_same_and_shuffled_input():
    farms = [
        FarmSupply(1, 100.0, feed_in_price_per_kwh=4.0),
        FarmSupply(2, 80.0, feed_in_price_per_kwh=4.2),
        FarmSupply(3, 60.0, feed_in_price_per_kwh=3.8),
    ]
    demands = [
        CustomerDemand(1, 120.0, green_target_type="re_percent", re_target_percent=50.0),
        CustomerDemand(2, 90.0, green_target_type="re_percent", re_target_percent=70.0),
    ]
    contracts = [
        _contract(1, "C1", 1, 1, price=4.6),
        _contract(2, "C2", 2, 1, price=4.9),
        _contract(3, "C3", 2, 2, price=4.7),
        _contract(4, "C4", 3, 2, price=5.1),
    ]
    a = optimize_period("2024-01", START, END, farms, demands, contracts, OPTS)
    b = optimize_period("2024-01", START, END, farms, demands, list(reversed(contracts)), OPTS)
    assert _alloc_map(a) == _alloc_map(b)


def test_optimizer_not_worse_than_greedy():
    farms = [
        FarmSupply(1, 100.0, feed_in_price_per_kwh=4.0),
        FarmSupply(2, 100.0, feed_in_price_per_kwh=4.0),
    ]
    demands = [CustomerDemand(1, 150.0, green_target_type="re_percent", re_target_percent=0.0)]
    # Greedy by priority would serve C1 (low margin) first; optimizer prefers C2.
    contracts = [
        _contract(1, "C1", 1, 1, price=4.2, priority=1),
        _contract(2, "C2", 2, 1, price=4.9, priority=2),
    ]

    def margin_of(alloc_map):
        m = 0.0
        for c in contracts:
            m += alloc_map.get(c.contract_id, 0.0) * 1000.0 * (c.price_per_kwh - 4.0)
        return m

    greedy = match_period("2024-01", START, END, farms, demands, contracts)
    opt = optimize_period("2024-01", START, END, farms, demands, contracts, OPTS)
    assert margin_of(_alloc_map(opt)) >= margin_of(_alloc_map(greedy)) - 1e-6


def test_empty_contracts_no_crash():
    farms = [FarmSupply(1, 100.0)]
    demands = [CustomerDemand(1, 100.0)]
    out = optimize_period("2024-01", START, END, farms, demands, [], OPTS)
    assert out.allocations == []
    assert out.objective_gross_margin_ntd == 0.0
    assert out.farm_summaries[0].unallocated_mwh == 100.0


def test_ineligible_contract_skipped():
    farms = [FarmSupply(1, 100.0, feed_in_price_per_kwh=4.0)]
    demands = [CustomerDemand(1, 100.0)]
    contracts = [
        ContractInput(
            contract_id=9,
            contract_number="X",
            wind_farm_id=1,
            customer_id=1,
            start_date=START,
            end_date=END,
            status="expired",
            price_per_kwh=4.5,
        )
    ]
    out = optimize_period("2024-01", START, END, farms, demands, contracts, OPTS)
    assert out.allocations == []
    assert len(out.skipped) == 1
    assert out.skipped[0].contract_id == 9
```

- [ ] **Step 2: 執行驗證失敗**

Run: `.venv/bin/python -m pytest tests/unit/test_optimizer.py -q`
Expected: FAIL(`ModuleNotFoundError: app.matching.optimizer`)

- [ ] **Step 3: 實作 optimizer.py**

Create `app/matching/optimizer.py`:

```python
"""MILP economic optimizer for monthly green-energy matching.

A pure function over the same dataclasses the greedy engine uses. Instead of a
priority order, it solves a mixed-integer linear program that maximizes the
retailer's gross margin, treats each customer's RE target as a (softened) hard
constraint, and supports two structural constraints: a minimum number of sites
per customer and a minimum per-site allocation share. See
``docs/matching-rules.md`` and the P3 design spec.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import pulp

from app.matching.engine import (
    Allocation,
    CustomerSummary,
    FarmSummary,
    MatchingOutcome,
    SkippedContract,
    _contract_limit,
    _EPS,
    _is_eligible,
    build_customer_summary,
    build_farm_summary,
)
from app.matching.engine import (
    ContractInput,
    CustomerDemand,
    FarmSupply,
)

_KWH = 1000.0
_P_RE = 1e6
_P_SITE = 1e3
_EPSILON = 1e-6


@dataclass
class CustomerTarget:
    customer_id: int
    re_target_mwh: float
    allocated_mwh: float
    re_shortfall_mwh: float
    re_target_met: bool
    sites_used: int
    site_shortfall: int


@dataclass
class OptimizationOutcome(MatchingOutcome):
    solver_status: str = "NotSolved"
    objective_gross_margin_ntd: float = 0.0
    customer_targets: list[CustomerTarget] = field(default_factory=list)


@dataclass
class OptimizeOptions:
    min_sites_per_customer: int = 0
    min_site_allocation_percent: float = 0.0
    default_feed_in_price_per_kwh: float = 4.0


def _re_target_mwh(demand: CustomerDemand) -> float:
    cons = demand.consumed_mwh
    ttype = demand.green_target_type or "re_percent"
    if ttype == "energy":
        target = demand.target_energy_mwh or 0.0
    else:
        target = (demand.re_target_percent or 0.0) / 100.0 * cons
    return min(cons, max(0.0, target))


def optimize_period(
    period: str,
    period_start: date,
    period_end: date,
    farms: list[FarmSupply],
    demands: list[CustomerDemand],
    contracts: list[ContractInput],
    options: OptimizeOptions,
) -> OptimizationOutcome:
    """Solve the monthly economic optimization and return a full outcome."""
    generation = {f.farm_id: f.generated_mwh for f in farms}
    consumption = {d.customer_id: d.consumed_mwh for d in demands}
    farm_by_id = {f.farm_id: f for f in farms}

    outcome = OptimizationOutcome(period=period)

    ordered = sorted(
        contracts, key=lambda c: (c.priority, c.start_date, c.contract_number)
    )
    eligible: list[ContractInput] = []
    for c in ordered:
        skip = _is_eligible(c, period_start, period_end)
        if skip is not None:
            outcome.skipped.append(
                SkippedContract(c.contract_id, c.contract_number, skip)
            )
        else:
            eligible.append(c)

    # ---- per-contract economics & caps ----
    def feedin(c: ContractInput) -> float:
        farm = farm_by_id.get(c.wind_farm_id)
        val = farm.feed_in_price_per_kwh if farm else None
        return val if val is not None else options.default_feed_in_price_per_kwh

    def price(c: ContractInput) -> float:
        return c.price_per_kwh if c.price_per_kwh is not None else feedin(c)

    def margin(c: ContractInput) -> float:
        return price(c) - feedin(c)

    def cap(c: ContractInput) -> float:
        gen = generation.get(c.wind_farm_id, 0.0)
        lim = _contract_limit(c, gen)
        if lim is None:
            return max(0.0, min(gen, consumption.get(c.customer_id, 0.0)))
        return max(0.0, lim)

    caps = {c.contract_id: cap(c) for c in eligible}

    # ---- decision variables ----
    prob = pulp.LpProblem("green_matching", pulp.LpMaximize)
    alloc = {
        c.contract_id: pulp.LpVariable(
            f"alloc_{c.contract_id}", lowBound=0.0, upBound=caps[c.contract_id]
        )
        for c in eligible
    }
    use = {
        c.contract_id: pulp.LpVariable(f"use_{c.contract_id}", cat="Binary")
        for c in eligible
    }

    contracts_by_customer: dict[int, list[ContractInput]] = {}
    contracts_by_farm: dict[int, list[ContractInput]] = {}
    for c in eligible:
        contracts_by_customer.setdefault(c.customer_id, []).append(c)
        contracts_by_farm.setdefault(c.wind_farm_id, []).append(c)

    # ---- constraints ----
    for fid, cs in contracts_by_farm.items():
        prob += pulp.lpSum(alloc[c.contract_id] for c in cs) <= generation.get(fid, 0.0)

    for kid, cs in contracts_by_customer.items():
        prob += pulp.lpSum(alloc[c.contract_id] for c in cs) <= consumption.get(kid, 0.0)

    for c in eligible:
        prob += alloc[c.contract_id] <= caps[c.contract_id] * use[c.contract_id]
        floor = options.min_site_allocation_percent / 100.0 * consumption.get(
            c.customer_id, 0.0
        )
        if floor > 0:
            prob += alloc[c.contract_id] >= floor * use[c.contract_id]

    re_short: dict[int, pulp.LpVariable] = {}
    site_short: dict[int, pulp.LpVariable] = {}
    for d in demands:
        kid = d.customer_id
        cs = contracts_by_customer.get(kid, [])
        rs = pulp.LpVariable(f"re_short_{kid}", lowBound=0.0)
        ss = pulp.LpVariable(f"site_short_{kid}", lowBound=0.0)
        re_short[kid] = rs
        site_short[kid] = ss
        prob += pulp.lpSum(alloc[c.contract_id] for c in cs) + rs >= _re_target_mwh(d)
        min_sites = min(options.min_sites_per_customer, len(cs))
        prob += pulp.lpSum(use[c.contract_id] for c in cs) + ss >= min_sites

    # ---- objective (scale-independent penalty hierarchy) ----
    max_abs_margin = max((abs(margin(c)) for c in eligible), default=0.0)
    margin_ub = max(
        1.0, sum(caps[c.contract_id] * _KWH * max_abs_margin for c in eligible)
    )
    margin_term = (
        pulp.lpSum(alloc[c.contract_id] * _KWH * margin(c) for c in eligible)
        / margin_ub
    )
    prob += (
        margin_term
        - _P_RE * pulp.lpSum(re_short.values())
        - _P_SITE * pulp.lpSum(site_short.values())
        - _EPSILON * pulp.lpSum(use.values())
    )

    prob.solve(pulp.PULP_CBC_CMD(msg=0, threads=1))
    outcome.solver_status = pulp.LpStatus[prob.status]

    # ---- extract allocations ----
    alloc_val = {
        c.contract_id: round(max(0.0, alloc[c.contract_id].value() or 0.0), 6)
        for c in eligible
    }
    farm_used: dict[int, float] = {}
    cust_used: dict[int, float] = {}
    for c in eligible:
        v = alloc_val[c.contract_id]
        farm_used[c.wind_farm_id] = farm_used.get(c.wind_farm_id, 0.0) + v
        cust_used[c.customer_id] = cust_used.get(c.customer_id, 0.0) + v

    def opt_reason(c: ContractInput) -> str:
        v = alloc_val[c.contract_id]
        if v <= _EPS:
            return "no allocation: not selected by optimizer"
        binding: list[str] = []
        if abs(farm_used.get(c.wind_farm_id, 0.0) - generation.get(c.wind_farm_id, 0.0)) <= _EPS:
            binding.append("wind farm supply")
        if abs(cust_used.get(c.customer_id, 0.0) - consumption.get(c.customer_id, 0.0)) <= _EPS:
            binding.append("customer demand")
        if abs(v - caps[c.contract_id]) <= _EPS:
            binding.append("contract cap")
        where = ", ".join(binding) if binding else "optimizer objective"
        return f"optimized {round(v, 3)} MWh (binding: {where})"

    gross_margin = 0.0
    for c in eligible:
        v = alloc_val[c.contract_id]
        gross_margin += v * _KWH * margin(c)
        lim = _contract_limit(c, generation.get(c.wind_farm_id, 0.0))
        outcome.allocations.append(
            Allocation(
                contract_id=c.contract_id,
                contract_number=c.contract_number,
                wind_farm_id=c.wind_farm_id,
                customer_id=c.customer_id,
                allocated_mwh=v,
                contract_limit_mwh=(None if lim is None else round(lim, 6)),
                reason=opt_reason(c),
            )
        )
    outcome.objective_gross_margin_ntd = round(gross_margin, 6)

    # ---- summaries & customer targets ----
    for d in demands:
        outcome.customer_summaries.append(
            build_customer_summary(
                d.customer_id, d.consumed_mwh, cust_used.get(d.customer_id, 0.0)
            )
        )
    for f in farms:
        outcome.farm_summaries.append(
            build_farm_summary(
                f.farm_id, f.generated_mwh, farm_used.get(f.farm_id, 0.0)
            )
        )

    for d in demands:
        kid = d.customer_id
        cs = contracts_by_customer.get(kid, [])
        target = _re_target_mwh(d)
        allocated = round(cust_used.get(kid, 0.0), 6)
        shortfall = round(max(0.0, target - allocated), 6)
        sites_used = sum(1 for c in cs if alloc_val[c.contract_id] > _EPS)
        min_sites = min(options.min_sites_per_customer, len(cs))
        outcome.customer_targets.append(
            CustomerTarget(
                customer_id=kid,
                re_target_mwh=round(target, 6),
                allocated_mwh=allocated,
                re_shortfall_mwh=shortfall,
                re_target_met=shortfall <= _EPS,
                sites_used=sites_used,
                site_shortfall=max(0, min_sites - sites_used),
            )
        )

    return outcome
```

> 注意:`_EPS`、`_is_eligible`、`_contract_limit` 為 `engine.py` 的模組級名稱(底線開頭),
> 匯入它們是刻意重用引擎既有邏輯以保持一致,不重寫。

- [ ] **Step 4: 匯出 optimizer 公開符號**

`app/matching/__init__.py` 追加(在既有 engine import 之後、`__all__` 內加對應項):

```python
from app.matching.optimizer import (
    CustomerTarget,
    OptimizationOutcome,
    OptimizeOptions,
    optimize_period,
)
```

並於 `__all__` list 加入 `"CustomerTarget"`, `"OptimizationOutcome"`, `"OptimizeOptions"`, `"optimize_period"`。

- [ ] **Step 5: 執行驗證通過**

Run: `.venv/bin/python -m pytest tests/unit/test_optimizer.py -q`
Expected: PASS(全部 12 個測試綠)

- [ ] **Step 6: 回歸全測試 + lint**

Run: `.venv/bin/python -m pytest tests/unit/test_matching_engine.py tests/unit/test_optimizer.py -q && .venv/bin/ruff check app/matching/optimizer.py`
Expected: PASS;ruff 無錯(`_EPS` 以 `from ... import _EPS` 匯入若被 ruff 視為未使用,確認實際有使用;`F401` 不應出現)。

- [ ] **Step 7: Commit**

```bash
git add app/matching/optimizer.py app/matching/__init__.py tests/unit/test_optimizer.py
git commit -m "feat(p3): add MILP economic optimizer (optimize_period)"
```

---

### Task 4: optimize_service — 從 DB 建輸入、求解、回 schema

**Files:**
- Create: `app/schemas/optimization.py`
- Create: `app/services/optimize_service.py`
- Test: `tests/integration/test_optimize_service.py`

**Interfaces:**
- Consumes: `optimize_period` / `OptimizeOptions` / `OptimizationOutcome`(Task 3);`matching_service.period_bounds` / `_sum_generation` / `_sum_consumption`(既有);ORM `WindFarm` / `Customer` / `Contract`。
- Produces:
  - `app/schemas/optimization.py`:`OptimizationResult` 及巢狀 `OptAllocation` / `OptCustomerTarget` / `OptCustomerSummary` / `OptFarmSummary`。
  - `optimize_service.compute_optimized(db, period, options: OptimizeOptions) -> OptimizationResult`

- [ ] **Step 1: 寫失敗測試**

Create `tests/integration/test_optimize_service.py`:

```python
"""Integration test: optimize_service against a seeded in-memory DB."""

from __future__ import annotations

from datetime import date

import pytest

from app.matching.optimizer import OptimizeOptions
from app.models import ConsumptionData, Contract, Customer, GenerationData, WindFarm
from app.models.enums import ContractStatus, GreenTargetType
from app.services import optimize_service


@pytest.fixture()
def seeded(db):
    f1 = WindFarm(code="F1", name="F1", installed_capacity_mw=100, feed_in_price_per_kwh=4.0)
    f2 = WindFarm(code="F2", name="F2", installed_capacity_mw=100, feed_in_price_per_kwh=4.0)
    cust = Customer(
        code="K1",
        company_name="K1",
        re_target_percent=50.0,
        green_target_type=GreenTargetType.RE_PERCENT,
    )
    db.add_all([f1, f2, cust])
    db.flush()
    db.add_all(
        [
            GenerationData(wind_farm_id=f1.id, period_start=date(2024, 1, 1), period_end=date(2024, 1, 31), generated_energy_mwh=100.0),
            GenerationData(wind_farm_id=f2.id, period_start=date(2024, 1, 1), period_end=date(2024, 1, 31), generated_energy_mwh=100.0),
            ConsumptionData(customer_id=cust.id, period_start=date(2024, 1, 1), period_end=date(2024, 1, 31), consumed_energy_mwh=100.0),
            Contract(contract_number="C1", wind_farm_id=f1.id, customer_id=cust.id, start_date=date(2024, 1, 1), end_date=date(2024, 12, 31), status=ContractStatus.ACTIVE, priority=100, contracted_percentage=100.0, price_per_kwh=4.3),
            Contract(contract_number="C2", wind_farm_id=f2.id, customer_id=cust.id, start_date=date(2024, 1, 1), end_date=date(2024, 12, 31), status=ContractStatus.ACTIVE, priority=100, contracted_percentage=100.0, price_per_kwh=4.9),
        ]
    )
    db.commit()
    return cust


def test_compute_optimized_prefers_high_margin(db, seeded):
    result = optimize_service.compute_optimized(
        db, "2024-01", OptimizeOptions(default_feed_in_price_per_kwh=4.0)
    )
    assert result.period == "2024-01"
    assert result.solver_status == "Optimal"
    by_num = {a.contract_number: a.allocated_mwh for a in result.allocations}
    assert by_num["C2"] == 100.0
    assert by_num["C1"] == 0.0
    assert result.objective_gross_margin_ntd == pytest.approx(90000.0, abs=1.0)
    ct = {c.customer_id: c for c in result.customer_targets}[seeded.id]
    assert ct.re_target_met is True


def test_compute_optimized_empty_period(db, seeded):
    result = optimize_service.compute_optimized(
        db, "2030-01", OptimizeOptions()
    )
    assert result.objective_gross_margin_ntd == 0.0
    assert all(a.allocated_mwh == 0.0 for a in result.allocations)
```

> 若 `db` fixture 不存在,沿用專案既有 conftest 的 DB fixture 命名(見
> `tests/integration/test_matching_service.py` 使用的 fixture),並改為相同名稱。

- [ ] **Step 2: 執行驗證失敗**

Run: `.venv/bin/python -m pytest tests/integration/test_optimize_service.py -q`
Expected: FAIL(`ModuleNotFoundError: app.services.optimize_service`)

- [ ] **Step 3: 建 schema**

Create `app/schemas/optimization.py`:

```python
"""Response schema for the economic-optimization endpoint (P3)."""

from __future__ import annotations

from pydantic import BaseModel


class OptAllocation(BaseModel):
    contract_id: int
    contract_number: str
    wind_farm_id: int
    customer_id: int
    allocated_mwh: float
    contract_limit_mwh: float | None
    reason: str


class OptCustomerTarget(BaseModel):
    customer_id: int
    re_target_mwh: float
    allocated_mwh: float
    re_shortfall_mwh: float
    re_target_met: bool
    sites_used: int
    site_shortfall: int


class OptCustomerSummary(BaseModel):
    customer_id: int
    consumption_mwh: float
    allocated_mwh: float
    achieved_re_percent: float


class OptFarmSummary(BaseModel):
    wind_farm_id: int
    generated_mwh: float
    allocated_mwh: float
    unallocated_mwh: float


class OptimizationResult(BaseModel):
    period: str
    solver_status: str
    objective_gross_margin_ntd: float
    min_sites_per_customer: int
    min_site_allocation_percent: float
    allocations: list[OptAllocation]
    customer_targets: list[OptCustomerTarget]
    customer_summaries: list[OptCustomerSummary]
    farm_summaries: list[OptFarmSummary]
```

- [ ] **Step 4: 建 service**

Create `app/services/optimize_service.py`:

```python
"""Economic-optimization service: load period data, solve, map to schema.

Pure read-side (compute-only, no persistence), mirroring evaluation service.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.matching.optimizer import OptimizeOptions, optimize_period
from app.models import Contract, Customer, WindFarm
from app.matching.engine import ContractInput, CustomerDemand, FarmSupply
from app.schemas.optimization import (
    OptAllocation,
    OptCustomerSummary,
    OptCustomerTarget,
    OptFarmSummary,
    OptimizationResult,
)
from app.services.matching_service import (
    _sum_consumption,
    _sum_generation,
    period_bounds,
)


def compute_optimized(
    db: Session, period: str, options: OptimizeOptions
) -> OptimizationResult:
    start, end = period_bounds(period)
    gen = _sum_generation(db, start, end)
    con = _sum_consumption(db, start, end)

    farms = [
        FarmSupply(
            farm_id=f.id,
            generated_mwh=gen.get(f.id, 0.0),
            feed_in_price_per_kwh=f.feed_in_price_per_kwh,
        )
        for f in db.execute(select(WindFarm).order_by(WindFarm.id)).scalars()
    ]
    demands = [
        CustomerDemand(
            customer_id=c.id,
            consumed_mwh=con.get(c.id, 0.0),
            green_target_type=c.green_target_type.value,
            re_target_percent=c.re_target_percent,
            target_energy_mwh=c.target_energy_mwh,
        )
        for c in db.execute(select(Customer).order_by(Customer.id)).scalars()
    ]
    contracts = [
        ContractInput(
            contract_id=c.id,
            contract_number=c.contract_number,
            wind_farm_id=c.wind_farm_id,
            customer_id=c.customer_id,
            start_date=c.start_date,
            end_date=c.end_date,
            status=c.status.value,
            priority=c.priority,
            contracted_energy_mwh=c.contracted_energy_mwh,
            contracted_percentage=c.contracted_percentage,
            price_per_kwh=c.price_per_kwh,
        )
        for c in db.execute(select(Contract).order_by(Contract.id)).scalars()
    ]

    outcome = optimize_period(period, start, end, farms, demands, contracts, options)

    return OptimizationResult(
        period=period,
        solver_status=outcome.solver_status,
        objective_gross_margin_ntd=outcome.objective_gross_margin_ntd,
        min_sites_per_customer=options.min_sites_per_customer,
        min_site_allocation_percent=options.min_site_allocation_percent,
        allocations=[
            OptAllocation(
                contract_id=a.contract_id,
                contract_number=a.contract_number,
                wind_farm_id=a.wind_farm_id,
                customer_id=a.customer_id,
                allocated_mwh=a.allocated_mwh,
                contract_limit_mwh=a.contract_limit_mwh,
                reason=a.reason,
            )
            for a in outcome.allocations
        ],
        customer_targets=[
            OptCustomerTarget(
                customer_id=t.customer_id,
                re_target_mwh=t.re_target_mwh,
                allocated_mwh=t.allocated_mwh,
                re_shortfall_mwh=t.re_shortfall_mwh,
                re_target_met=t.re_target_met,
                sites_used=t.sites_used,
                site_shortfall=t.site_shortfall,
            )
            for t in outcome.customer_targets
        ],
        customer_summaries=[
            OptCustomerSummary(
                customer_id=s.customer_id,
                consumption_mwh=s.consumption_mwh,
                allocated_mwh=s.allocated_mwh,
                achieved_re_percent=s.achieved_re_percent,
            )
            for s in outcome.customer_summaries
        ],
        farm_summaries=[
            OptFarmSummary(
                wind_farm_id=s.farm_id,
                generated_mwh=s.generated_mwh,
                allocated_mwh=s.allocated_mwh,
                unallocated_mwh=s.unallocated_mwh,
            )
            for s in outcome.farm_summaries
        ],
    )
```

- [ ] **Step 5: 執行驗證通過**

Run: `.venv/bin/python -m pytest tests/integration/test_optimize_service.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app/schemas/optimization.py app/services/optimize_service.py tests/integration/test_optimize_service.py
git commit -m "feat(p3): add optimize_service and optimization response schema"
```

---

### Task 5: API 端點 GET /matching/optimize

**Files:**
- Modify: `app/api/v1/matching.py`(加 optimize 路由)
- Test: `tests/integration/test_optimize_api.py`

**Interfaces:**
- Consumes: `optimize_service.compute_optimized`、`OptimizeOptions`、`OptimizationResult`、`settings`。
- Produces: `GET /api/v1/matching/optimize?period=&min_sites=&min_site_allocation_percent=` → `OptimizationResult`。

- [ ] **Step 1: 寫失敗測試**

Create `tests/integration/test_optimize_api.py`:

```python
"""API test for GET /api/v1/matching/optimize."""

from __future__ import annotations

from datetime import date

import pytest

from app.models import ConsumptionData, Contract, Customer, GenerationData, WindFarm
from app.models.enums import ContractStatus, GreenTargetType


@pytest.fixture()
def seeded(db):
    f1 = WindFarm(code="F1", name="F1", installed_capacity_mw=100, feed_in_price_per_kwh=4.0)
    f2 = WindFarm(code="F2", name="F2", installed_capacity_mw=100, feed_in_price_per_kwh=4.0)
    cust = Customer(code="K1", company_name="K1", re_target_percent=50.0, green_target_type=GreenTargetType.RE_PERCENT)
    db.add_all([f1, f2, cust])
    db.flush()
    db.add_all(
        [
            GenerationData(wind_farm_id=f1.id, period_start=date(2024, 1, 1), period_end=date(2024, 1, 31), generated_energy_mwh=100.0),
            GenerationData(wind_farm_id=f2.id, period_start=date(2024, 1, 1), period_end=date(2024, 1, 31), generated_energy_mwh=100.0),
            ConsumptionData(customer_id=cust.id, period_start=date(2024, 1, 1), period_end=date(2024, 1, 31), consumed_energy_mwh=100.0),
            Contract(contract_number="C1", wind_farm_id=f1.id, customer_id=cust.id, start_date=date(2024, 1, 1), end_date=date(2024, 12, 31), status=ContractStatus.ACTIVE, priority=100, contracted_percentage=100.0, price_per_kwh=4.3),
            Contract(contract_number="C2", wind_farm_id=f2.id, customer_id=cust.id, start_date=date(2024, 1, 1), end_date=date(2024, 12, 31), status=ContractStatus.ACTIVE, priority=100, contracted_percentage=100.0, price_per_kwh=4.9),
        ]
    )
    db.commit()


def test_optimize_endpoint_returns_full_structure(client, seeded):
    resp = client.get("/api/v1/matching/optimize", params={"period": "2024-01"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["period"] == "2024-01"
    assert body["solver_status"] == "Optimal"
    assert "objective_gross_margin_ntd" in body
    assert len(body["customer_targets"]) == 1
    by_num = {a["contract_number"]: a["allocated_mwh"] for a in body["allocations"]}
    assert by_num["C2"] == 100.0


def test_optimize_endpoint_min_sites_query(client, seeded):
    resp = client.get(
        "/api/v1/matching/optimize", params={"period": "2024-01", "min_sites": 2}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["min_sites_per_customer"] == 2
    assert body["customer_targets"][0]["sites_used"] == 2


def test_optimize_endpoint_empty_period(client, seeded):
    resp = client.get("/api/v1/matching/optimize", params={"period": "2030-01"})
    assert resp.status_code == 200
    assert resp.json()["objective_gross_margin_ntd"] == 0.0
```

> `client` / `db` fixture 沿用既有 conftest(見 `tests/integration/test_evaluation_api.py`);
> 若名稱不同請對齊既有命名。

- [ ] **Step 2: 執行驗證失敗**

Run: `.venv/bin/python -m pytest tests/integration/test_optimize_api.py -q`
Expected: FAIL(404 Not Found,路由不存在)

- [ ] **Step 3: 加路由**

`app/api/v1/matching.py` import 區塊加:

```python
from app.core.config import settings
from app.matching.optimizer import OptimizeOptions
from app.schemas.optimization import OptimizationResult
from app.services import optimize_service
```

在檔案末尾加路由:

```python
@router.get("/optimize", response_model=OptimizationResult)
def optimize(
    period: str = Query(..., examples=["2024-01"], description="Period 'YYYY-MM'"),
    min_sites: int | None = Query(default=None, ge=0),
    min_site_allocation_percent: float | None = Query(default=None, ge=0.0, le=100.0),
    db: Session = Depends(get_db),
) -> OptimizationResult:
    """Global economic-optimization matching for a period (compute-only)."""
    options = OptimizeOptions(
        min_sites_per_customer=(
            settings.optimize_min_sites_per_customer
            if min_sites is None
            else min_sites
        ),
        min_site_allocation_percent=(
            settings.optimize_min_site_allocation_percent
            if min_site_allocation_percent is None
            else min_site_allocation_percent
        ),
        default_feed_in_price_per_kwh=settings.default_feed_in_price_per_kwh,
    )
    return optimize_service.compute_optimized(db, period, options)
```

- [ ] **Step 4: 執行驗證通過**

Run: `.venv/bin/python -m pytest tests/integration/test_optimize_api.py -q`
Expected: PASS

- [ ] **Step 5: 全套件回歸**

Run: `.venv/bin/python -m pytest -q`
Expected: 全綠(既有 + 新增)。

- [ ] **Step 6: Commit**

```bash
git add app/api/v1/matching.py tests/integration/test_optimize_api.py
git commit -m "feat(p3): add GET /matching/optimize endpoint"
```

---

### Task 6: 儀表板頁 — 最佳化 + 並列對比優先序

**Files:**
- Modify: `dashboard/api_client.py`(加 `optimize`)
- Create: `dashboard/pages/7_Optimization.py`

**Interfaces:**
- Consumes: 後端 `GET /matching/optimize`;既有 `run_matching` / `analytics_summary` / `analytics_customers`(用於並列對比優先序引擎的毛利與平均 RE%)。
- Produces: `api_client.optimize(period, min_sites=None, min_site_allocation_percent=None) -> dict`。

- [ ] **Step 1: 加 api_client 方法**

`dashboard/api_client.py` 在 `live_renewables` 之前(或 `evaluation` 之後)加:

```python
def optimize(
    period: str,
    min_sites: int | None = None,
    min_site_allocation_percent: float | None = None,
) -> dict:
    params: dict = {"period": period}
    if min_sites is not None:
        params["min_sites"] = min_sites
    if min_site_allocation_percent is not None:
        params["min_site_allocation_percent"] = min_site_allocation_percent
    return _get(f"{V1}/matching/optimize", **params)
```

- [ ] **Step 2: 建儀表板頁**

Create `dashboard/pages/7_Optimization.py`:

```python
"""最佳化媒合:全域經濟最佳化,並與優先序引擎並列對比。"""

from __future__ import annotations

import pandas as pd
import streamlit as st

import api_client
from api_client import ApiError

st.set_page_config(page_title="最佳化媒合", page_icon="🎯", layout="wide")
st.title("🎯 經濟最佳化媒合(P3)")
st.caption(
    "以 MILP 全域最佳化:目標為售電端毛利最大,RE 目標為硬約束(不可行時退為軟約束),"
    "並支援「最少案場數 / 最小分配%」結構約束。"
)

col_a, col_b, col_c = st.columns(3)
period = col_a.text_input("期間 (YYYY-MM)", value="2024-01")
min_sites = col_b.number_input("最少案場數 / 客戶", min_value=0, max_value=10, value=0, step=1)
min_pct = col_c.number_input(
    "最小分配% (佔客戶用電)", min_value=0.0, max_value=100.0, value=0.0, step=1.0
)

if st.button("執行最佳化", type="primary"):
    try:
        opt = api_client.optimize(
            period,
            min_sites=int(min_sites) or None,
            min_site_allocation_percent=float(min_pct) or None,
        )
    except ApiError as exc:
        st.error(str(exc))
        st.stop()

    st.subheader("求解結果")
    m1, m2 = st.columns(2)
    m1.metric("售電端總毛利 (NTD)", f"{opt['objective_gross_margin_ntd']:,.0f}")
    m2.metric("求解狀態", opt["solver_status"])

    targets = opt["customer_targets"]
    if targets:
        st.markdown("**各客戶 RE 目標達成**")
        st.dataframe(
            pd.DataFrame(targets).rename(
                columns={
                    "customer_id": "客戶ID",
                    "re_target_mwh": "RE目標(MWh)",
                    "allocated_mwh": "分配(MWh)",
                    "re_shortfall_mwh": "缺口(MWh)",
                    "re_target_met": "達標",
                    "sites_used": "使用案場數",
                    "site_shortfall": "案場缺口",
                }
            ),
            use_container_width=True,
            hide_index=True,
        )

    st.markdown("**分配明細**")
    st.dataframe(
        pd.DataFrame(opt["allocations"]),
        use_container_width=True,
        hide_index=True,
    )

    # ---- 並列對比:優先序引擎 ----
    st.subheader("策略對比:優先序 vs 最佳化")
    try:
        run = api_client.run_matching(period)
        summary = run.get("result_summary", {}) or {}
        greedy_re = summary.get("average_re_percent", 0.0)
        greedy_alloc = summary.get("total_allocated_mwh", 0.0)
    except ApiError as exc:
        st.info(f"無法取得優先序對比:{exc}")
        greedy_re = greedy_alloc = None

    opt_alloc = sum(a["allocated_mwh"] for a in opt["allocations"])
    opt_avg_re = (
        sum(t["allocated_mwh"] for t in targets)
        / sum(s["consumption_mwh"] for s in opt["customer_summaries"])
        * 100.0
        if opt["customer_summaries"]
        and sum(s["consumption_mwh"] for s in opt["customer_summaries"]) > 0
        else 0.0
    )
    compare = pd.DataFrame(
        [
            {
                "策略": "優先序 (greedy)",
                "總分配 (MWh)": greedy_alloc,
                "平均 RE %": greedy_re,
            },
            {
                "策略": "全域最佳化 (MILP)",
                "總分配 (MWh)": round(opt_alloc, 3),
                "平均 RE %": round(opt_avg_re, 3),
            },
        ]
    )
    st.dataframe(compare, use_container_width=True, hide_index=True)
    st.caption(
        "最佳化以毛利為目標並保證 RE 硬約束,優先序則依合約 priority;兩者分配策略不同。"
    )
```

- [ ] **Step 3: 手動冒煙驗證(Streamlit 頁無單元測試,屬 TDD 例外)**

啟動後端與儀表板,開 `http://localhost:8501` 的「最佳化媒合」頁,輸入 `2024-01`、按「執行最佳化」,確認:求解狀態 `Optimal`、毛利數值、各客戶達標表、分配明細、策略對比表皆正常顯示;調 `最少案場數=2` 後 `使用案場數` 反映變化。

Run(背景啟動):
```bash
.venv/bin/uvicorn app.main:app --port 8000 &
.venv/bin/streamlit run dashboard/Home.py --server.port 8501
```
Expected: 頁面正常渲染、無例外。

- [ ] **Step 4: Commit**

```bash
git add dashboard/api_client.py dashboard/pages/7_Optimization.py
git commit -m "feat(p3): add optimization dashboard page with greedy comparison"
```

---

### Task 7: 文件更新(README + matching-rules)

**Files:**
- Modify: `README.md`(Known limitations、API 表)
- Modify: `docs/matching-rules.md`(新增 optimizer 章節)

**Interfaces:** 無程式碼介面;純文件。

- [ ] **Step 1: 更新 README 的 API 表**

在 `README.md` 的 API 表(`| GET | /api/v1/analytics/evaluation...` 那列之後)加一列:

```markdown
| GET | `/api/v1/matching/optimize?period=&min_sites=&min_site_allocation_percent=` | Global economic-optimization matching (MILP): maximize retailer gross margin with RE targets as constraints; dashboard "Optimization" page renders it |
```

- [ ] **Step 2: 更新 README 的 Known limitations**

把:

```markdown
- Greedy priority allocation, not a global optimum.
```

改為:

```markdown
- Two matching strategies: deterministic priority (greedy) and global economic
  optimization (MILP, `GET /matching/optimize`). The greedy engine is the audit
  baseline; the optimizer maximizes retailer gross margin under RE and structural
  constraints.
```

- [ ] **Step 3: 在 matching-rules.md 加 optimizer 章節**

於 `docs/matching-rules.md` 末尾加一節(繁中),說明:目標(售電毛利最大)、變數(alloc/use)、
約束(場供給/客戶需求/合約上限/最小分配%);RE 與最少案場以 slack 軟化 + 大懲罰(可行時等效
硬約束);正規化懲罰階層 `P_re ≫ P_site ≫ margin ≫ ε`;determinism(單執行緒 CBC + 穩定建模序 +
ε 破平局)。內容 200–300 字即可,對齊
`docs/superpowers/specs/2026-07-16-p3-optimization-matching-design.md` 的 formulation。

- [ ] **Step 4: 驗證文件連結與格式**

Run: `.venv/bin/python -m pytest -q`(確認文件變更未影響測試)
Expected: 全綠。

- [ ] **Step 5: Commit**

```bash
git add README.md docs/matching-rules.md
git commit -m "docs(p3): document the economic optimizer and update limitations"
```

---

## 自審備註(writing-plans self-review)

- **Spec 覆蓋**:資料模型(Task 2)、MILP formulation/目標/約束/determinism(Task 3)、
  服務 compute-only(Task 4)、API(Task 5)、儀表板並列對比(Task 6)、設定與相依(Task 1)、
  文件(Task 7)——皆對應。
- **型別一致**:`OptimizeOptions` / `OptimizationOutcome` / `CustomerTarget` /
  `optimize_period` 簽章在 Task 3 定義,Task 4/5 一致沿用;schema 欄位與 outcome 欄位逐一對映。
- **無 placeholder**:每個程式步驟含完整程式碼。
- **既有行為保護**:Task 2 明列既有引擎測試須回歸綠;Task 5 跑全套件。
- **fixture 假設**:Task 4/5 假設既有 `db` / `client` conftest fixture;已註記若命名不同須對齊
  `tests/integration/test_evaluation_api.py`。實作前若 fixture 名稱不符,以既有為準。
