# P4a 時段時間電價媒合 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增台電三段式時間電價(尖峰/半尖峰/離峰 × 夏月/非夏月)的**逐時段貪婪媒合**路徑,產出時段別發用電、跨時段 RE、時段別經濟(用逐時段灰電價),月度引擎/優先序/P3 MILP 全不動。

**Architecture:** 新純函式模組 `slot_engine.match_slots`(重用 engine 的資格/上限/reason/summary helper);gen/consumption 加可空 `time_slot`(時段列與月度列互斥、加總=月度→月度引擎不受影響);`slot_matching_service`(compute-only)→ `GET /matching/slots` + 時段媒合儀表板頁 + `generate_slot_profiles` 產生器。

**Tech Stack:** Python 3.12 · SQLAlchemy 2 · Alembic · Pydantic 2 · FastAPI · Streamlit · pytest。

## Global Constraints

- 語言:面向使用者字串與文件用**繁體中文(zh-TW)**;程式碼識別字用英文。
- `app/matching/engine.py::match_period` 行為**不得改變**;既有測試須全綠。
- `slot_engine` 為**純函式、無 I/O、deterministic**:同輸入(含打亂 farms/demands/contracts 順序)→ 完全相同分配(round 6 位後比較)。
- compute-only:**不新增媒合結果資料表、不落地**(比照 evaluation / P3)。
- 時段:`TimeSlot{peak, half_peak, off_peak}`;季別 `Season{summer, non_summer}` 由月份推導(夏月=6–9)。`SLOT_ORDER=(PEAK, HALF_PEAK, OFF_PEAK)` 固定序(determinism + 尖峰先取用月度能量預算)。
- `time_slot` 欄可空;**時段列與月度列互斥、時段列加總=月度總量**(產生器維持此不變式)。
- 度數 = MWh × 1000;金額 NTD;分配 `round(..., 6)`;容差 `_EPS=1e-9`(沿用 engine)。
- 綠電轉供價 P4a 用合約 `price_per_kwh`(單一費率);TOU 價值由**逐時段灰電價**體現。收購價用 `farm.feed_in_price_per_kwh` 或 `settings.default_feed_in_price_per_kwh`。
- 重用 `engine` 既有:`_is_eligible`、`_EPS`、`build_customer_summary`、`build_farm_summary`、`ContractInput`、`SkippedContract`、`CustomerSummary`、`FarmSummary`。不重寫。

---

### Task 1: 時段/季別 enum + tou 模組

**Files:**
- Modify: `app/models/enums.py`(加 `TimeSlot`、`Season`)
- Create: `app/matching/tou.py`(`season_of`、`SLOT_ORDER`、`GREY_TOU_PRICES`、`grey_price`)
- Test: `tests/unit/test_tou.py`

**Interfaces:**
- Produces:
  - `enums.TimeSlot{PEAK="peak", HALF_PEAK="half_peak", OFF_PEAK="off_peak"}`、`enums.Season{SUMMER="summer", NON_SUMMER="non_summer"}`
  - `tou.SLOT_ORDER: tuple[TimeSlot, ...]`、`tou.season_of(month: int) -> Season`、`tou.grey_price(season: Season, slot: TimeSlot) -> float`、`tou.GREY_TOU_PRICES: dict`

- [ ] **Step 1: 寫失敗測試**

Create `tests/unit/test_tou.py`:

```python
"""Unit tests for time-of-use slot/season helpers."""

from __future__ import annotations

import pytest

from app.matching.tou import GREY_TOU_PRICES, SLOT_ORDER, grey_price, season_of
from app.models.enums import Season, TimeSlot


@pytest.mark.parametrize(
    "month, expected",
    [(5, Season.NON_SUMMER), (6, Season.SUMMER), (9, Season.SUMMER), (10, Season.NON_SUMMER)],
)
def test_season_of_boundaries(month, expected):
    assert season_of(month) == expected


def test_slot_order_is_peak_first():
    assert SLOT_ORDER == (TimeSlot.PEAK, TimeSlot.HALF_PEAK, TimeSlot.OFF_PEAK)


def test_grey_price_summer_peak_is_highest():
    summer_peak = grey_price(Season.SUMMER, TimeSlot.PEAK)
    summer_off = grey_price(Season.SUMMER, TimeSlot.OFF_PEAK)
    assert summer_peak > summer_off
    # every (season, slot) combination is defined
    assert len(GREY_TOU_PRICES) == len(Season) * len(TimeSlot)
```

- [ ] **Step 2: 執行驗證失敗**

Run: `.venv/bin/python -m pytest tests/unit/test_tou.py -q`
Expected: FAIL(`ImportError`/`AttributeError`:`TimeSlot` / `app.matching.tou` 不存在)

- [ ] **Step 3: 加 enum**

`app/models/enums.py` 末尾加:

```python


class TimeSlot(StrEnum):
    PEAK = "peak"
    HALF_PEAK = "half_peak"
    OFF_PEAK = "off_peak"


class Season(StrEnum):
    SUMMER = "summer"
    NON_SUMMER = "non_summer"
```

- [ ] **Step 4: 建 tou 模組**

Create `app/matching/tou.py`:

```python
"""Time-of-use helpers: season derivation, slot order, TOU grey reference prices.

Season follows Taipower's summer window (Jun 1 – Sep 30). Grey prices are
illustrative demo values (NTD/kWh) roughly matching Taipower's high-voltage
time-of-use tariff magnitudes; they are configurable in real use.
"""

from __future__ import annotations

from app.models.enums import Season, TimeSlot

SLOT_ORDER: tuple[TimeSlot, ...] = (
    TimeSlot.PEAK,
    TimeSlot.HALF_PEAK,
    TimeSlot.OFF_PEAK,
)

GREY_TOU_PRICES: dict[tuple[Season, TimeSlot], float] = {
    (Season.SUMMER, TimeSlot.PEAK): 5.0,
    (Season.SUMMER, TimeSlot.HALF_PEAK): 3.5,
    (Season.SUMMER, TimeSlot.OFF_PEAK): 1.8,
    (Season.NON_SUMMER, TimeSlot.PEAK): 4.7,
    (Season.NON_SUMMER, TimeSlot.HALF_PEAK): 3.4,
    (Season.NON_SUMMER, TimeSlot.OFF_PEAK): 1.7,
}


def season_of(month: int) -> Season:
    """Taipower summer months are June through September (6–9)."""
    return Season.SUMMER if 6 <= month <= 9 else Season.NON_SUMMER


def grey_price(season: Season, slot: TimeSlot) -> float:
    return GREY_TOU_PRICES[(season, slot)]
```

- [ ] **Step 5: 執行驗證通過**

Run: `.venv/bin/python -m pytest tests/unit/test_tou.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app/models/enums.py app/matching/tou.py tests/unit/test_tou.py
git commit -m "feat(p4a): add TimeSlot/Season enums and TOU grey-price helpers"
```

---

### Task 2: gen/consumption 加 time_slot 欄 + migration

**Files:**
- Modify: `app/models/generation.py`、`app/models/consumption.py`(加 `time_slot`)
- Modify: `app/schemas/generation.py`、`app/schemas/consumption.py`(加可選 `time_slot`)
- Create: `alembic/versions/<hash>_add_time_slot.py`
- Test: `tests/integration/test_time_slot_column.py`

**Interfaces:**
- Produces:`GenerationData.time_slot: TimeSlot | None`、`ConsumptionData.time_slot: TimeSlot | None`;schema `GenerationBase.time_slot`、`ConsumptionBase.time_slot`(可選)。

- [ ] **Step 1: 寫失敗測試**

Create `tests/integration/test_time_slot_column.py`:

```python
"""time_slot column: nullable, round-trips, monthly engine unaffected."""

from __future__ import annotations

from datetime import date

from app.models import ConsumptionData, Customer, GenerationData, WindFarm
from app.models.enums import TimeSlot


def test_time_slot_defaults_none_and_persists(db):
    f = WindFarm(code="F1", name="F1", installed_capacity_mw=100)
    c = Customer(code="K1", company_name="K1")
    db.add_all([f, c])
    db.flush()
    g_month = GenerationData(
        wind_farm_id=f.id, period_start=date(2024, 1, 1), period_end=date(2024, 1, 31),
        generated_energy_mwh=90.0,
    )
    g_slot = GenerationData(
        wind_farm_id=f.id, period_start=date(2024, 1, 1), period_end=date(2024, 1, 31),
        generated_energy_mwh=30.0, time_slot=TimeSlot.PEAK,
    )
    db.add_all([g_month, g_slot])
    db.commit()
    assert g_month.time_slot is None
    assert g_slot.time_slot == TimeSlot.PEAK


def test_consumption_time_slot(db):
    c = Customer(code="K2", company_name="K2")
    db.add(c)
    db.flush()
    row = ConsumptionData(
        customer_id=c.id, period_start=date(2024, 1, 1), period_end=date(2024, 1, 31),
        consumed_energy_mwh=10.0, time_slot=TimeSlot.OFF_PEAK,
    )
    db.add(row)
    db.commit()
    assert row.time_slot == TimeSlot.OFF_PEAK
```

- [ ] **Step 2: 執行驗證失敗**

Run: `.venv/bin/python -m pytest tests/integration/test_time_slot_column.py -q`
Expected: FAIL(`TypeError: 'time_slot' is an invalid keyword argument for GenerationData`)

- [ ] **Step 3: 加 model 欄位**

`app/models/generation.py`:import 區加 `from sqlalchemy import Enum as SAEnum` 與 `from app.models.enums import TimeSlot`,並在 `data_source` 之後加:

```python
    time_slot: Mapped[TimeSlot | None] = mapped_column(
        SAEnum(TimeSlot), default=None, nullable=True
    )
```

`app/models/consumption.py` 同樣加相同 import 與欄位(接在 `data_source` 後)。

- [ ] **Step 4: 加 schema 欄位**

`app/schemas/generation.py`:import 加 `from app.models.enums import TimeSlot`;`GenerationBase` 於 `data_source` 後加:

```python
    time_slot: TimeSlot | None = None
```

`app/schemas/consumption.py` 比照(讀該檔既有結構,於 `data_source` 後加相同欄位;若無 `data_source` 欄則加在能量欄之後)。

- [ ] **Step 5: 產生 migration**

Run: `.venv/bin/alembic revision --autogenerate -m "add time_slot to gen/consumption"`
接著**檢查並修正**產生的檔案,確保兩表都用 `batch_alter_table` 加**可空** enum 欄(比照 `fa6b9882de2c` 的 enum 寫法):

```python
def upgrade() -> None:
    with op.batch_alter_table("generation_data", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("time_slot", sa.Enum("PEAK", "HALF_PEAK", "OFF_PEAK", name="timeslot"), nullable=True)
        )
    with op.batch_alter_table("consumption_data", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("time_slot", sa.Enum("PEAK", "HALF_PEAK", "OFF_PEAK", name="timeslot"), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("consumption_data", schema=None) as batch_op:
        batch_op.drop_column("time_slot")
    with op.batch_alter_table("generation_data", schema=None) as batch_op:
        batch_op.drop_column("time_slot")
```

- [ ] **Step 6: 套用 migration + 驗證通過**

Run: `.venv/bin/alembic upgrade head && .venv/bin/python -m pytest tests/integration/test_time_slot_column.py -q`
Expected: PASS

- [ ] **Step 7: 回歸 + Commit**

Run: `.venv/bin/python -m pytest -q`(既有測試全綠)
```bash
git add app/models/generation.py app/models/consumption.py app/schemas/generation.py app/schemas/consumption.py alembic/versions/ tests/integration/test_time_slot_column.py
git commit -m "feat(p4a): add nullable time_slot to generation/consumption + migration"
```

---

### Task 3: slot_engine — 逐時段貪婪媒合(核心)

**Files:**
- Create: `app/matching/slot_engine.py`
- Test: `tests/unit/test_slot_engine.py`

**Interfaces:**
- Consumes:`app.matching.engine`(`ContractInput`、`SkippedContract`、`CustomerSummary`、`FarmSummary`、`_is_eligible`、`_EPS`、`build_customer_summary`、`build_farm_summary`);`app.matching.tou`(`SLOT_ORDER`、`season_of`)。
- Produces:`SlotFarmSupply`、`SlotCustomerDemand`、`SlotAllocation`、`SlotSubtotal`、`SlotMatchingOutcome`、`match_slots(...)`。

- [ ] **Step 1: 寫失敗測試**

Create `tests/unit/test_slot_engine.py`:

```python
"""Unit tests for the per-time-slot greedy matcher."""

from __future__ import annotations

from datetime import date

from app.matching.engine import ContractInput
from app.matching.slot_engine import (
    SlotCustomerDemand,
    SlotFarmSupply,
    match_slots,
)
from app.models.enums import Season, TimeSlot

START = date(2024, 1, 1)   # January -> NON_SUMMER
END = date(2024, 1, 31)


def _contract(cid, num, farm, cust, energy=None, pct=None, priority=100):
    return ContractInput(
        contract_id=cid, contract_number=num, wind_farm_id=farm, customer_id=cust,
        start_date=START, end_date=END, status="active", priority=priority,
        contracted_energy_mwh=energy, contracted_percentage=pct, price_per_kwh=4.5,
    )


def _supply(farm, **per_slot):
    return [SlotFarmSupply(farm, s, mwh) for s, mwh in per_slot.items()]


def _demand(cust, **per_slot):
    return [SlotCustomerDemand(cust, s, mwh) for s, mwh in per_slot.items()]


def _amap(outcome):
    return {(a.contract_id, a.slot): a.allocated_mwh for a in outcome.allocations}


def test_per_slot_min_allocation():
    farms = _supply(1, **{TimeSlot.PEAK: 40.0, TimeSlot.HALF_PEAK: 30.0, TimeSlot.OFF_PEAK: 20.0})
    demands = _demand(1, **{TimeSlot.PEAK: 25.0, TimeSlot.HALF_PEAK: 50.0, TimeSlot.OFF_PEAK: 10.0})
    contracts = [_contract(1, "C1", 1, 1, pct=100.0)]
    out = match_slots("2024-01", START, END, farms, demands, contracts)
    a = _amap(out)
    assert a[(1, TimeSlot.PEAK)] == 25.0      # limited by demand
    assert a[(1, TimeSlot.HALF_PEAK)] == 30.0  # limited by farm supply
    assert a[(1, TimeSlot.OFF_PEAK)] == 10.0   # limited by demand
    assert out.season == Season.NON_SUMMER


def test_eq5_transfer_not_exceed_slot_generation():
    farms = _supply(1, **{TimeSlot.PEAK: 5.0, TimeSlot.HALF_PEAK: 5.0, TimeSlot.OFF_PEAK: 5.0})
    demands = _demand(1, **{TimeSlot.PEAK: 100.0, TimeSlot.HALF_PEAK: 100.0, TimeSlot.OFF_PEAK: 100.0})
    contracts = [_contract(1, "C1", 1, 1, pct=100.0)]
    out = match_slots("2024-01", START, END, farms, demands, contracts)
    for a in out.allocations:
        assert a.allocated_mwh <= 5.0 + 1e-9


def test_monthly_energy_budget_shared_across_slots_peak_first():
    # contract monthly energy cap 30; peak slot consumes it first
    farms = _supply(1, **{TimeSlot.PEAK: 100.0, TimeSlot.HALF_PEAK: 100.0, TimeSlot.OFF_PEAK: 100.0})
    demands = _demand(1, **{TimeSlot.PEAK: 100.0, TimeSlot.HALF_PEAK: 100.0, TimeSlot.OFF_PEAK: 100.0})
    contracts = [_contract(1, "C1", 1, 1, energy=30.0)]
    out = match_slots("2024-01", START, END, farms, demands, contracts)
    a = _amap(out)
    assert a[(1, TimeSlot.PEAK)] == 30.0
    assert a[(1, TimeSlot.HALF_PEAK)] == 0.0
    assert a[(1, TimeSlot.OFF_PEAK)] == 0.0
    total = sum(x.allocated_mwh for x in out.allocations)
    assert total == 30.0


def test_percentage_cap_per_slot():
    farms = _supply(1, **{TimeSlot.PEAK: 100.0, TimeSlot.HALF_PEAK: 100.0, TimeSlot.OFF_PEAK: 100.0})
    demands = _demand(1, **{TimeSlot.PEAK: 100.0, TimeSlot.HALF_PEAK: 100.0, TimeSlot.OFF_PEAK: 100.0})
    contracts = [_contract(1, "C1", 1, 1, pct=40.0)]
    out = match_slots("2024-01", START, END, farms, demands, contracts)
    for a in out.allocations:
        assert a.allocated_mwh == 40.0  # 40% of each slot's 100


def test_cross_slot_re_aggregation():
    farms = _supply(1, **{TimeSlot.PEAK: 50.0, TimeSlot.HALF_PEAK: 50.0, TimeSlot.OFF_PEAK: 50.0})
    demands = _demand(1, **{TimeSlot.PEAK: 100.0, TimeSlot.HALF_PEAK: 100.0, TimeSlot.OFF_PEAK: 100.0})
    contracts = [_contract(1, "C1", 1, 1, pct=100.0)]
    out = match_slots("2024-01", START, END, farms, demands, contracts)
    cs = {c.customer_id: c for c in out.customer_summaries}[1]
    assert cs.consumption_mwh == 300.0
    assert cs.allocated_mwh == 150.0
    assert cs.achieved_re_percent == 50.0


def test_deterministic_shuffled_inputs():
    farms = (
        _supply(1, **{TimeSlot.PEAK: 40.0, TimeSlot.HALF_PEAK: 30.0, TimeSlot.OFF_PEAK: 60.0})
        + _supply(2, **{TimeSlot.PEAK: 20.0, TimeSlot.HALF_PEAK: 25.0, TimeSlot.OFF_PEAK: 15.0})
    )
    demands = (
        _demand(1, **{TimeSlot.PEAK: 30.0, TimeSlot.HALF_PEAK: 40.0, TimeSlot.OFF_PEAK: 50.0})
        + _demand(2, **{TimeSlot.PEAK: 20.0, TimeSlot.HALF_PEAK: 20.0, TimeSlot.OFF_PEAK: 20.0})
    )
    contracts = [
        _contract(1, "C1", 1, 1, pct=80.0, priority=1),
        _contract(2, "C2", 2, 1, pct=100.0, priority=2),
        _contract(3, "C3", 2, 2, pct=100.0, priority=3),
    ]
    a = match_slots("2024-01", START, END, farms, demands, contracts)
    b = match_slots("2024-01", START, END, list(reversed(farms)), list(reversed(demands)), list(reversed(contracts)))
    assert _amap(a) == _amap(b)


def test_ineligible_skipped_and_empty_no_crash():
    farms = _supply(1, **{TimeSlot.PEAK: 10.0})
    demands = _demand(1, **{TimeSlot.PEAK: 10.0})
    expired = ContractInput(
        contract_id=9, contract_number="X", wind_farm_id=1, customer_id=1,
        start_date=START, end_date=END, status="expired", price_per_kwh=4.5,
    )
    out = match_slots("2024-01", START, END, farms, demands, [expired])
    assert out.allocations == []
    assert len(out.skipped) == 1
    empty = match_slots("2024-01", START, END, [], [], [])
    assert empty.allocations == []
    assert empty.customer_summaries == []
```

- [ ] **Step 2: 執行驗證失敗**

Run: `.venv/bin/python -m pytest tests/unit/test_slot_engine.py -q`
Expected: FAIL(`ModuleNotFoundError: app.matching.slot_engine`)

- [ ] **Step 3: 實作 slot_engine.py**

Create `app/matching/slot_engine.py`:

```python
"""Per-time-slot greedy green-energy matcher (pure, deterministic).

Runs the same greedy min(farm, customer, cap) allocation as the monthly engine,
but per Taipower time slot (peak / half-peak / off-peak) within a month. A
contract's percentage cap applies per slot (patent eq.3); its monthly energy cap
is a budget shared across slots (peak first). RE aggregates across slots
(patent eq.6). The monthly engine is untouched; helpers are reused from engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from app.matching.engine import (
    ContractInput,
    CustomerSummary,
    FarmSummary,
    SkippedContract,
    _EPS,
    _is_eligible,
    build_customer_summary,
    build_farm_summary,
)
from app.matching.tou import SLOT_ORDER, season_of
from app.models.enums import Season, TimeSlot


@dataclass(frozen=True)
class SlotFarmSupply:
    farm_id: int
    slot: TimeSlot
    generated_mwh: float


@dataclass(frozen=True)
class SlotCustomerDemand:
    customer_id: int
    slot: TimeSlot
    consumed_mwh: float


@dataclass
class SlotAllocation:
    contract_id: int
    contract_number: str
    wind_farm_id: int
    customer_id: int
    slot: TimeSlot
    allocated_mwh: float
    reason: str


@dataclass
class SlotSubtotal:
    slot: TimeSlot
    customer_summaries: list[CustomerSummary]
    farm_summaries: list[FarmSummary]


@dataclass
class SlotMatchingOutcome:
    period: str
    season: Season
    allocations: list[SlotAllocation] = field(default_factory=list)
    skipped: list[SkippedContract] = field(default_factory=list)
    customer_summaries: list[CustomerSummary] = field(default_factory=list)
    farm_summaries: list[FarmSummary] = field(default_factory=list)
    slot_subtotals: list[SlotSubtotal] = field(default_factory=list)


def _slot_reason(
    alloc: float,
    farm_rem: float,
    cust_rem: float,
    pct_cap: float,
    energy_cap: float,
) -> str:
    if alloc <= _EPS:
        if farm_rem <= _EPS:
            return "no allocation: farm slot generation exhausted"
        if cust_rem <= _EPS:
            return "no allocation: customer slot demand met"
        if pct_cap <= _EPS:
            return "no allocation: contract percentage cap is zero"
        if energy_cap <= _EPS:
            return "no allocation: contract monthly energy budget exhausted"
        return "no allocation"
    binding: list[str] = []
    if abs(alloc - farm_rem) <= _EPS:
        binding.append("farm slot supply")
    if abs(alloc - cust_rem) <= _EPS:
        binding.append("customer slot demand")
    if pct_cap != float("inf") and abs(alloc - pct_cap) <= _EPS:
        binding.append("contract percentage cap")
    if energy_cap != float("inf") and abs(alloc - energy_cap) <= _EPS:
        binding.append("contract monthly energy budget")
    where = ", ".join(binding) if binding else "available supply"
    return f"allocated {round(alloc, 3)} MWh (limited by {where})"


def match_slots(
    period: str,
    period_start: date,
    period_end: date,
    farms: list[SlotFarmSupply],
    demands: list[SlotCustomerDemand],
    contracts: list[ContractInput],
) -> SlotMatchingOutcome:
    season = season_of(period_start.month)
    outcome = SlotMatchingOutcome(period=period, season=season)

    gen: dict[tuple[int, TimeSlot], float] = {}
    for f in farms:
        gen[(f.farm_id, f.slot)] = gen.get((f.farm_id, f.slot), 0.0) + f.generated_mwh
    con: dict[tuple[int, TimeSlot], float] = {}
    for d in demands:
        con[(d.customer_id, d.slot)] = (
            con.get((d.customer_id, d.slot), 0.0) + d.consumed_mwh
        )

    farm_ids = sorted({f.farm_id for f in farms})
    cust_ids = sorted({d.customer_id for d in demands})

    remaining_gen = dict(gen)
    alloc_cust_slot: dict[tuple[int, TimeSlot], float] = {}
    remaining_energy: dict[int, float] = {}

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
            continue
        eligible.append(c)
        if c.contracted_energy_mwh is not None:
            remaining_energy[c.contract_id] = c.contracted_energy_mwh

    INF = float("inf")
    for slot in SLOT_ORDER:
        for c in eligible:
            farm_gen_slot = gen.get((c.wind_farm_id, slot), 0.0)
            farm_rem = remaining_gen.get((c.wind_farm_id, slot), 0.0)
            cust_rem = con.get((c.customer_id, slot), 0.0) - alloc_cust_slot.get(
                (c.customer_id, slot), 0.0
            )
            pct_cap = (
                c.contracted_percentage / 100.0 * farm_gen_slot
                if c.contracted_percentage is not None
                else INF
            )
            energy_cap = remaining_energy.get(c.contract_id, INF)

            candidates = [max(0.0, farm_rem), max(0.0, cust_rem)]
            if pct_cap != INF:
                candidates.append(max(0.0, pct_cap))
            if energy_cap != INF:
                candidates.append(max(0.0, energy_cap))
            alloc = round(min(candidates), 6)

            outcome.allocations.append(
                SlotAllocation(
                    contract_id=c.contract_id,
                    contract_number=c.contract_number,
                    wind_farm_id=c.wind_farm_id,
                    customer_id=c.customer_id,
                    slot=slot,
                    allocated_mwh=alloc,
                    reason=_slot_reason(alloc, farm_rem, cust_rem, pct_cap, energy_cap),
                )
            )
            if alloc > 0:
                remaining_gen[(c.wind_farm_id, slot)] = farm_rem - alloc
                alloc_cust_slot[(c.customer_id, slot)] = (
                    alloc_cust_slot.get((c.customer_id, slot), 0.0) + alloc
                )
                if c.contract_id in remaining_energy:
                    remaining_energy[c.contract_id] -= alloc

    for slot in SLOT_ORDER:
        cs = [
            build_customer_summary(
                cid,
                con.get((cid, slot), 0.0),
                alloc_cust_slot.get((cid, slot), 0.0),
            )
            for cid in cust_ids
        ]
        fs = [
            build_farm_summary(
                fid,
                gen.get((fid, slot), 0.0),
                gen.get((fid, slot), 0.0) - remaining_gen.get((fid, slot), 0.0),
            )
            for fid in farm_ids
        ]
        outcome.slot_subtotals.append(SlotSubtotal(slot, cs, fs))

    for cid in cust_ids:
        consumed = sum(con.get((cid, s), 0.0) for s in SLOT_ORDER)
        allocated = sum(alloc_cust_slot.get((cid, s), 0.0) for s in SLOT_ORDER)
        outcome.customer_summaries.append(
            build_customer_summary(cid, consumed, allocated)
        )
    for fid in farm_ids:
        generated = sum(gen.get((fid, s), 0.0) for s in SLOT_ORDER)
        allocated = sum(
            gen.get((fid, s), 0.0) - remaining_gen.get((fid, s), 0.0)
            for s in SLOT_ORDER
        )
        outcome.farm_summaries.append(build_farm_summary(fid, generated, allocated))

    return outcome
```

- [ ] **Step 4: 執行驗證通過**

Run: `.venv/bin/python -m pytest tests/unit/test_slot_engine.py -q`
Expected: PASS(全部綠)

- [ ] **Step 5: 回歸 + lint + Commit**

Run: `.venv/bin/python -m pytest -q && .venv/bin/ruff check app tests && .venv/bin/black --check app tests`
Expected: 全綠、lint 乾淨(如有需要先 `black app tests`)。
```bash
git add app/matching/slot_engine.py tests/unit/test_slot_engine.py
git commit -m "feat(p4a): add per-time-slot greedy matcher (match_slots)"
```

---

### Task 4: slot_matching_service + schema

**Files:**
- Create: `app/schemas/slot_matching.py`
- Create: `app/services/slot_matching_service.py`
- Test: `tests/integration/test_slot_matching_service.py`

**Interfaces:**
- Consumes:`slot_engine.match_slots`、`tou.grey_price`、`matching_service.period_bounds`、ORM `WindFarm`/`Customer`/`Contract`/`GenerationData`/`ConsumptionData`、`ContractInput`、`settings`。
- Produces:`app/schemas/slot_matching.py::SlotMatchingResult`;`slot_matching_service.compute_slot_outcome(db, period) -> SlotMatchingResult`。

- [ ] **Step 1: 寫失敗測試**

Create `tests/integration/test_slot_matching_service.py`:

```python
"""Integration test: slot_matching_service against a seeded DB (slot rows)."""

from __future__ import annotations

from datetime import date

import pytest

from app.models import ConsumptionData, Contract, Customer, GenerationData, WindFarm
from app.models.enums import ContractStatus, TimeSlot
from app.services import slot_matching_service


@pytest.fixture()
def seeded(db):
    f = WindFarm(code="F1", name="F1", installed_capacity_mw=100, feed_in_price_per_kwh=4.0)
    cust = Customer(code="K1", company_name="K1", re_target_percent=100.0)
    db.add_all([f, cust])
    db.flush()
    for slot, gmwh, cmwh in [
        (TimeSlot.PEAK, 40.0, 50.0),
        (TimeSlot.HALF_PEAK, 30.0, 30.0),
        (TimeSlot.OFF_PEAK, 60.0, 20.0),
    ]:
        db.add(GenerationData(wind_farm_id=f.id, period_start=date(2024, 1, 1), period_end=date(2024, 1, 31), generated_energy_mwh=gmwh, time_slot=slot))
        db.add(ConsumptionData(customer_id=cust.id, period_start=date(2024, 1, 1), period_end=date(2024, 1, 31), consumed_energy_mwh=cmwh, time_slot=slot))
    db.add(Contract(contract_number="C1", wind_farm_id=f.id, customer_id=cust.id, start_date=date(2024, 1, 1), end_date=date(2024, 12, 31), status=ContractStatus.ACTIVE, priority=100, contracted_percentage=100.0, price_per_kwh=4.8))
    db.commit()
    return cust


def test_compute_slot_outcome_structure(db, seeded):
    r = slot_matching_service.compute_slot_outcome(db, "2024-01")
    assert r.period == "2024-01"
    assert r.season == "non_summer"
    # peak: min(40,50)=40; half:min(30,30)=30; off:min(60,20)=20 -> total 90
    cs = {c.customer_id: c for c in r.customer_summaries}[seeded.id]
    assert cs.allocated_mwh == 90.0
    assert cs.consumption_mwh == 100.0
    assert cs.achieved_re_percent == 90.0
    # seller margin = 90 MWh * 1000 * (4.8 - 4.0) = 72000
    assert r.seller_gross_margin_ntd == pytest.approx(72000.0, abs=1.0)
    assert len(r.slot_breakdown) == 3


def test_compute_slot_outcome_empty_period(db, seeded):
    r = slot_matching_service.compute_slot_outcome(db, "2030-01")
    assert r.seller_gross_margin_ntd == 0.0
    assert all(c.allocated_mwh == 0.0 for c in r.customer_summaries) or r.customer_summaries == []
```

- [ ] **Step 2: 執行驗證失敗**

Run: `.venv/bin/python -m pytest tests/integration/test_slot_matching_service.py -q`
Expected: FAIL(`ModuleNotFoundError: app.services.slot_matching_service`)

- [ ] **Step 3: 建 schema**

Create `app/schemas/slot_matching.py`:

```python
"""Response schema for the time-slot matching endpoint (P4a)."""

from __future__ import annotations

from pydantic import BaseModel


class SlotAllocationOut(BaseModel):
    contract_id: int
    contract_number: str
    wind_farm_id: int
    customer_id: int
    slot: str
    allocated_mwh: float
    reason: str


class CustomerSummaryOut(BaseModel):
    customer_id: int
    consumption_mwh: float
    allocated_mwh: float
    achieved_re_percent: float


class FarmSummaryOut(BaseModel):
    wind_farm_id: int
    generated_mwh: float
    allocated_mwh: float
    unallocated_mwh: float


class SlotBreakdown(BaseModel):
    slot: str
    grey_price_per_kwh: float
    customer_summaries: list[CustomerSummaryOut]
    farm_summaries: list[FarmSummaryOut]


class BuyerSide(BaseModel):
    re_percent: float
    avg_price_per_kwh: float
    added_cost: float


class SlotMatchingResult(BaseModel):
    period: str
    season: str
    allocations: list[SlotAllocationOut]
    customer_summaries: list[CustomerSummaryOut]
    farm_summaries: list[FarmSummaryOut]
    slot_breakdown: list[SlotBreakdown]
    seller_gross_margin_ntd: float
    buyer: BuyerSide
```

- [ ] **Step 4: 建 service**

Create `app/services/slot_matching_service.py`:

```python
"""Time-slot matching service: load slot rows, match, compute TOU economics.

Compute-only (no persistence), mirroring evaluation / optimize services.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.matching.engine import ContractInput
from app.matching.slot_engine import (
    SlotCustomerDemand,
    SlotFarmSupply,
    match_slots,
)
from app.matching.tou import grey_price
from app.models import Contract, ConsumptionData, Customer, GenerationData, WindFarm
from app.schemas.slot_matching import (
    BuyerSide,
    CustomerSummaryOut,
    FarmSummaryOut,
    SlotAllocationOut,
    SlotBreakdown,
    SlotMatchingResult,
)
from app.services.matching_service import period_bounds

_KWH = 1000.0


def compute_slot_outcome(db: Session, period: str) -> SlotMatchingResult:
    start, end = period_bounds(period)

    gen_rows = db.execute(
        select(GenerationData).where(
            GenerationData.period_start >= start,
            GenerationData.period_start <= end,
            GenerationData.time_slot.is_not(None),
        )
    ).scalars()
    farms = [
        SlotFarmSupply(g.wind_farm_id, g.time_slot, g.generated_energy_mwh)
        for g in gen_rows
    ]
    con_rows = db.execute(
        select(ConsumptionData).where(
            ConsumptionData.period_start >= start,
            ConsumptionData.period_start <= end,
            ConsumptionData.time_slot.is_not(None),
        )
    ).scalars()
    demands = [
        SlotCustomerDemand(c.customer_id, c.time_slot, c.consumed_energy_mwh)
        for c in con_rows
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

    outcome = match_slots(period, start, end, farms, demands, contracts)

    feedin = {f.id: f.feed_in_price_per_kwh for f in db.execute(select(WindFarm)).scalars()}
    price = {c.id: (c.price_per_kwh or 0.0) for c in db.execute(select(Contract)).scalars()}
    default_feed = settings.default_feed_in_price_per_kwh

    # seller gross margin (sum over slot allocations)
    seller_margin = 0.0
    for a in outcome.allocations:
        if a.allocated_mwh <= 0:
            continue
        feed = feedin.get(a.wind_farm_id)
        feed = feed if feed is not None else default_feed
        seller_margin += a.allocated_mwh * _KWH * (price.get(a.contract_id, 0.0) - feed)

    # buyer TOU economics
    total_kwh = sum(c.consumption_mwh for c in outcome.customer_summaries) * _KWH
    green_kwh = sum(c.allocated_mwh for c in outcome.customer_summaries) * _KWH

    # green cost & added cost: per allocation, using that slot's grey price
    green_cost = 0.0
    added_cost = 0.0
    for a in outcome.allocations:
        if a.allocated_mwh <= 0:
            continue
        kwh = a.allocated_mwh * _KWH
        p = price.get(a.contract_id, 0.0)
        g = grey_price(outcome.season, a.slot)
        green_cost += kwh * p
        added_cost += kwh * (p - g)

    # grey cost: per slot, unmatched consumption priced at that slot's grey price
    grey_cost = 0.0
    for sub in outcome.slot_subtotals:
        g = grey_price(outcome.season, sub.slot)
        slot_green = sum(cs.allocated_mwh for cs in sub.customer_summaries) * _KWH
        slot_consumed = sum(cs.consumption_mwh for cs in sub.customer_summaries) * _KWH
        grey_cost += max(0.0, slot_consumed - slot_green) * g

    re_percent = (green_kwh / total_kwh * 100.0) if total_kwh else 0.0
    avg_price = ((green_cost + grey_cost) / total_kwh) if total_kwh else 0.0

    return SlotMatchingResult(
        period=period,
        season=outcome.season.value,
        allocations=[
            SlotAllocationOut(
                contract_id=a.contract_id,
                contract_number=a.contract_number,
                wind_farm_id=a.wind_farm_id,
                customer_id=a.customer_id,
                slot=a.slot.value,
                allocated_mwh=a.allocated_mwh,
                reason=a.reason,
            )
            for a in outcome.allocations
        ],
        customer_summaries=[
            CustomerSummaryOut(
                customer_id=s.customer_id,
                consumption_mwh=s.consumption_mwh,
                allocated_mwh=s.allocated_mwh,
                achieved_re_percent=s.achieved_re_percent,
            )
            for s in outcome.customer_summaries
        ],
        farm_summaries=[
            FarmSummaryOut(
                wind_farm_id=s.farm_id,
                generated_mwh=s.generated_mwh,
                allocated_mwh=s.allocated_mwh,
                unallocated_mwh=s.unallocated_mwh,
            )
            for s in outcome.farm_summaries
        ],
        slot_breakdown=[
            SlotBreakdown(
                slot=sub.slot.value,
                grey_price_per_kwh=grey_price(outcome.season, sub.slot),
                customer_summaries=[
                    CustomerSummaryOut(
                        customer_id=cs.customer_id,
                        consumption_mwh=cs.consumption_mwh,
                        allocated_mwh=cs.allocated_mwh,
                        achieved_re_percent=cs.achieved_re_percent,
                    )
                    for cs in sub.customer_summaries
                ],
                farm_summaries=[
                    FarmSummaryOut(
                        wind_farm_id=fs.farm_id,
                        generated_mwh=fs.generated_mwh,
                        allocated_mwh=fs.allocated_mwh,
                        unallocated_mwh=fs.unallocated_mwh,
                    )
                    for fs in sub.farm_summaries
                ],
            )
            for sub in outcome.slot_subtotals
        ],
        seller_gross_margin_ntd=round(seller_margin, 6),
        buyer=BuyerSide(
            re_percent=round(re_percent, 4),
            avg_price_per_kwh=round(avg_price, 4),
            added_cost=round(added_cost, 2),
        ),
    )
```

> 經濟語意:`green_cost`/`added_cost` 逐 allocation(用該時段灰電價)計;`grey_cost`
> 逐時段(未媒合度數 × 該時段灰電價)計;`avg_price = (green_cost + grey_cost) / 總度數`。
> 售電端毛利只用綠電轉供價 − 收購價(不含灰電、不含輸電費,輸電費留 P5)。

- [ ] **Step 5: 執行驗證通過**

Run: `.venv/bin/python -m pytest tests/integration/test_slot_matching_service.py -q`
Expected: PASS

- [ ] **Step 6: lint + Commit**

Run: `.venv/bin/black app tests && .venv/bin/ruff check app tests`
```bash
git add app/schemas/slot_matching.py app/services/slot_matching_service.py tests/integration/test_slot_matching_service.py
git commit -m "feat(p4a): add slot_matching_service with TOU economics + schema"
```

---

### Task 5: API GET /matching/slots

**Files:**
- Modify: `app/api/v1/matching.py`
- Test: `tests/integration/test_slot_matching_api.py`

**Interfaces:**
- Consumes:`slot_matching_service.compute_slot_outcome`、`SlotMatchingResult`。
- Produces:`GET /api/v1/matching/slots?period=` → `SlotMatchingResult`。

- [ ] **Step 1: 寫失敗測試**

Create `tests/integration/test_slot_matching_api.py`:

```python
"""API test for GET /api/v1/matching/slots."""

from __future__ import annotations

from datetime import date

import pytest

from app.models import ConsumptionData, Contract, Customer, GenerationData, WindFarm
from app.models.enums import ContractStatus, TimeSlot


@pytest.fixture()
def seeded(db):
    f = WindFarm(code="F1", name="F1", installed_capacity_mw=100, feed_in_price_per_kwh=4.0)
    cust = Customer(code="K1", company_name="K1", re_target_percent=100.0)
    db.add_all([f, cust])
    db.flush()
    for slot, g, c in [(TimeSlot.PEAK, 40.0, 50.0), (TimeSlot.HALF_PEAK, 30.0, 30.0), (TimeSlot.OFF_PEAK, 60.0, 20.0)]:
        db.add(GenerationData(wind_farm_id=f.id, period_start=date(2024, 1, 1), period_end=date(2024, 1, 31), generated_energy_mwh=g, time_slot=slot))
        db.add(ConsumptionData(customer_id=cust.id, period_start=date(2024, 1, 1), period_end=date(2024, 1, 31), consumed_energy_mwh=c, time_slot=slot))
    db.add(Contract(contract_number="C1", wind_farm_id=f.id, customer_id=cust.id, start_date=date(2024, 1, 1), end_date=date(2024, 12, 31), status=ContractStatus.ACTIVE, priority=100, contracted_percentage=100.0, price_per_kwh=4.8))
    db.commit()


def test_slots_endpoint(client, seeded):
    resp = client.get("/api/v1/matching/slots", params={"period": "2024-01"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["period"] == "2024-01"
    assert body["season"] == "non_summer"
    assert len(body["slot_breakdown"]) == 3
    assert body["customer_summaries"][0]["allocated_mwh"] == 90.0
    assert body["seller_gross_margin_ntd"] > 0


def test_slots_endpoint_empty(client, seeded):
    resp = client.get("/api/v1/matching/slots", params={"period": "2030-01"})
    assert resp.status_code == 200
    assert resp.json()["seller_gross_margin_ntd"] == 0.0
```

- [ ] **Step 2: 執行驗證失敗**

Run: `.venv/bin/python -m pytest tests/integration/test_slot_matching_api.py -q`
Expected: FAIL(404)

- [ ] **Step 3: 加路由**

`app/api/v1/matching.py` import 區加:

```python
from app.schemas.slot_matching import SlotMatchingResult
from app.services import slot_matching_service
```

檔末加:

```python
@router.get("/slots", response_model=SlotMatchingResult)
def slots(
    period: str = Query(..., examples=["2024-01"], description="Period 'YYYY-MM'"),
    db: Session = Depends(get_db),
) -> SlotMatchingResult:
    """Per-time-slot (TOU) matching for a period (compute-only)."""
    return slot_matching_service.compute_slot_outcome(db, period)
```

- [ ] **Step 4: 執行驗證通過 + 全套件**

Run: `.venv/bin/python -m pytest tests/integration/test_slot_matching_api.py -q && .venv/bin/python -m pytest -q`
Expected: 全綠。

- [ ] **Step 5: Commit**

```bash
git add app/api/v1/matching.py tests/integration/test_slot_matching_api.py
git commit -m "feat(p4a): add GET /matching/slots endpoint"
```

---

### Task 6: 時段 profile 產生器

**Files:**
- Create: `scripts/generate_slot_profiles.py`
- Test: `tests/integration/test_slot_profiles.py`

**Interfaces:**
- Produces:`generate_slot_profiles.split_profiles(db)`(把月度 gen/consumption 就地拆成時段列,維持加總=月度、互斥)。CLI `python -m scripts.generate_slot_profiles`。

- [ ] **Step 1: 寫失敗測試**

Create `tests/integration/test_slot_profiles.py`:

```python
"""Slot profile generator: sums to monthly, mutually exclusive, deterministic;
and the monthly engine still totals correctly on slot data."""

from __future__ import annotations

from datetime import date

from app.models import ConsumptionData, Contract, Customer, GenerationData, WindFarm
from app.models.enums import ContractStatus
from app.services.matching_service import compute_outcome
from scripts.generate_slot_profiles import split_profiles


def _seed_monthly(db):
    f = WindFarm(code="F1", name="F1", installed_capacity_mw=100, feed_in_price_per_kwh=4.0)
    cust = Customer(code="K1", company_name="K1", re_target_percent=100.0)
    db.add_all([f, cust])
    db.flush()
    db.add(GenerationData(wind_farm_id=f.id, period_start=date(2024, 1, 1), period_end=date(2024, 1, 31), generated_energy_mwh=100.0))
    db.add(ConsumptionData(customer_id=cust.id, period_start=date(2024, 1, 1), period_end=date(2024, 1, 31), consumed_energy_mwh=80.0))
    db.add(Contract(contract_number="C1", wind_farm_id=f.id, customer_id=cust.id, start_date=date(2024, 1, 1), end_date=date(2024, 12, 31), status=ContractStatus.ACTIVE, priority=100, contracted_percentage=100.0, price_per_kwh=4.8))
    db.commit()
    return f, cust


def test_split_sums_to_monthly_and_mutually_exclusive(db):
    f, cust = _seed_monthly(db)
    split_profiles(db)
    gens = db.query(GenerationData).filter(GenerationData.wind_farm_id == f.id).all()
    # monthly row replaced by 3 slot rows summing to 100
    assert all(g.time_slot is not None for g in gens)
    assert len(gens) == 3
    assert round(sum(g.generated_energy_mwh for g in gens), 6) == 100.0


def test_monthly_engine_still_totals_on_slot_data(db):
    f, cust = _seed_monthly(db)
    split_profiles(db)
    outcome = compute_outcome(db, "2024-01")
    farm = {s.farm_id: s for s in outcome.farm_summaries}[f.id]
    assert farm.generated_mwh == 100.0  # monthly engine sums slot rows back to monthly


def test_deterministic(db):
    f, cust = _seed_monthly(db)
    split_profiles(db)
    first = sorted(
        (g.time_slot.value, g.generated_energy_mwh)
        for g in db.query(GenerationData).all()
    )
    # re-running on already-split data is idempotent (no monthly rows remain to split)
    split_profiles(db)
    second = sorted(
        (g.time_slot.value, g.generated_energy_mwh)
        for g in db.query(GenerationData).all()
    )
    assert first == second
```

- [ ] **Step 2: 執行驗證失敗**

Run: `.venv/bin/python -m pytest tests/integration/test_slot_profiles.py -q`
Expected: FAIL(`ModuleNotFoundError: scripts.generate_slot_profiles`)

- [ ] **Step 3: 建產生器**

Create `scripts/generate_slot_profiles.py`:

```python
"""Split monthly generation/consumption rows into time-slot rows (deterministic).

Wind-typical slot ratios: generation skews to off-peak (night); consumption
skews to peak (industrial daytime). Slot rows replace the monthly row so the
mutual-exclusivity invariant holds (slot rows sum to the monthly total). The
last slot absorbs rounding so the sum is exact. Idempotent: rows already tagged
with a time_slot are left alone.

Usage:
    python -m scripts.generate_slot_profiles
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models import ConsumptionData, GenerationData
from app.models.enums import TimeSlot

GEN_RATIOS = {TimeSlot.PEAK: 0.25, TimeSlot.HALF_PEAK: 0.30, TimeSlot.OFF_PEAK: 0.45}
CON_RATIOS = {TimeSlot.PEAK: 0.40, TimeSlot.HALF_PEAK: 0.35, TimeSlot.OFF_PEAK: 0.25}
_ORDER = (TimeSlot.PEAK, TimeSlot.HALF_PEAK, TimeSlot.OFF_PEAK)


def _split_total(total: float, ratios: dict[TimeSlot, float]) -> dict[TimeSlot, float]:
    out: dict[TimeSlot, float] = {}
    running = 0.0
    for slot in _ORDER[:-1]:
        v = round(total * ratios[slot], 6)
        out[slot] = v
        running += v
    out[_ORDER[-1]] = round(total - running, 6)  # last absorbs rounding
    return out


def split_profiles(db: Session) -> None:
    for g in list(
        db.execute(
            select(GenerationData).where(GenerationData.time_slot.is_(None))
        ).scalars()
    ):
        for slot, mwh in _split_total(g.generated_energy_mwh, GEN_RATIOS).items():
            db.add(
                GenerationData(
                    wind_farm_id=g.wind_farm_id,
                    period_start=g.period_start,
                    period_end=g.period_end,
                    generated_energy_mwh=mwh,
                    data_source=g.data_source,
                    time_slot=slot,
                )
            )
        db.delete(g)
    for c in list(
        db.execute(
            select(ConsumptionData).where(ConsumptionData.time_slot.is_(None))
        ).scalars()
    ):
        for slot, mwh in _split_total(c.consumed_energy_mwh, CON_RATIOS).items():
            db.add(
                ConsumptionData(
                    customer_id=c.customer_id,
                    period_start=c.period_start,
                    period_end=c.period_end,
                    consumed_energy_mwh=mwh,
                    data_source=c.data_source,
                    time_slot=slot,
                )
            )
        db.delete(c)
    db.commit()


def main() -> None:
    db = SessionLocal()
    try:
        split_profiles(db)
        print("split monthly rows into time-slot profiles")
    finally:
        db.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 執行驗證通過**

Run: `.venv/bin/python -m pytest tests/integration/test_slot_profiles.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/generate_slot_profiles.py tests/integration/test_slot_profiles.py
git commit -m "feat(p4a): add deterministic monthly->time-slot profile generator"
```

---

### Task 7: 儀表板頁「時段媒合」

**Files:**
- Modify: `dashboard/api_client.py`(加 `slot_matching`)
- Create: `dashboard/pages/8_時段媒合.py`

**Interfaces:**
- Consumes:`GET /matching/slots`。
- Produces:`api_client.slot_matching(period) -> dict`。

- [ ] **Step 1: 加 api_client 方法**

`dashboard/api_client.py` 於 `def optimize(...)` 之後加:

```python
def slot_matching(period: str) -> dict:
    return _get(f"{V1}/matching/slots", period=period)
```

- [ ] **Step 2: 建頁面**

Create `dashboard/pages/8_時段媒合.py`:

```python
"""時段媒合:台電三段式時間電價逐時段媒合與時段別經濟。"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard import api_client as api

st.set_page_config(page_title="時段媒合", page_icon="⏱️", layout="wide")
st.title("⏱️ 時段時間電價媒合(P4a)")
st.caption(
    "台電三段式時間電價(尖峰/半尖峰/離峰 × 夏月/非夏月)逐時段媒合。"
    "RE 跨時段加總;用電端成本用逐時段灰電價,凸顯尖峰綠電的較高價值。"
)

period = st.text_input("期間 (YYYY-MM)", value="2024-01")

if st.button("執行時段媒合", type="primary"):
    try:
        r = api.slot_matching(period)
    except api.ApiError as exc:
        st.error(str(exc))
        st.stop()

    m1, m2, m3 = st.columns(3)
    m1.metric("季別", "夏月" if r["season"] == "summer" else "非夏月")
    m2.metric("售電端總毛利 (NTD)", f"{r['seller_gross_margin_ntd']:,.0f}")
    m3.metric("用電端 RE", f"{r['buyer']['re_percent']:.2f}%")

    st.markdown("#### 各客戶 RE 達成(跨時段)")
    st.dataframe(
        pd.DataFrame(r["customer_summaries"]).rename(
            columns={
                "customer_id": "客戶 ID",
                "consumption_mwh": "用電量 (MWh)",
                "allocated_mwh": "已分配 (MWh)",
                "achieved_re_percent": "RE 達成率 (%)",
            }
        ),
        use_container_width=True,
        hide_index=True,
    )

    st.markdown("#### 時段別明細")
    for sub in r["slot_breakdown"]:
        label = {"peak": "尖峰", "half_peak": "半尖峰", "off_peak": "離峰"}[sub["slot"]]
        st.markdown(f"**{label}** · 灰電價 {sub['grey_price_per_kwh']} NTD/kWh")
        st.dataframe(
            pd.DataFrame(sub["customer_summaries"]).rename(
                columns={
                    "customer_id": "客戶 ID",
                    "consumption_mwh": "用電量 (MWh)",
                    "allocated_mwh": "已分配 (MWh)",
                    "achieved_re_percent": "RE 達成率 (%)",
                }
            ),
            use_container_width=True,
            hide_index=True,
        )

    st.markdown("#### 分配明細(逐時段)")
    st.dataframe(
        pd.DataFrame(r["allocations"]).rename(
            columns={
                "contract_number": "合約編號",
                "wind_farm_id": "風場 ID",
                "customer_id": "客戶 ID",
                "slot": "時段",
                "allocated_mwh": "已分配 (MWh)",
                "reason": "分配原因",
            }
        ),
        use_container_width=True,
        hide_index=True,
    )
```

- [ ] **Step 3: 冒煙驗證(UI 屬 TDD 例外)**

Run: `PYTHONPATH=. .venv/bin/python -c "import ast; ast.parse(open('dashboard/pages/8_時段媒合.py',encoding='utf-8').read()); ast.parse(open('dashboard/api_client.py',encoding='utf-8').read()); print('syntax OK')"`
接著 `.venv/bin/python -m pytest -q`(全套件不受影響)。

- [ ] **Step 4: Commit**

```bash
git add dashboard/api_client.py "dashboard/pages/8_時段媒合.py"
git commit -m "feat(p4a): add time-slot matching dashboard page"
```

---

### Task 8: 文件(README + matching-rules + 專利對應)

**Files:**
- Modify: `README.md`(API 表加 `/matching/slots`;Known limitations 更新)
- Modify: `docs/matching-rules.md`(新增時段媒合章節 + 專利對應)

**Interfaces:** 純文件。

- [ ] **Step 1: README API 表加列**

在 `/matching/optimize` 那列之後加:

```markdown
| GET | `/api/v1/matching/slots?period=` | Per-time-slot (Taipower TOU) matching: peak/half-peak/off-peak × summer/non-summer, cross-slot RE and per-slot economics; dashboard "時段媒合" page renders it |
```

- [ ] **Step 2: README Known limitations 更新**

把「Monthly matching only (no 8760-hour time-matching yet).」改為:

```markdown
- Monthly matching plus a Taipower three-tier time-of-use slot matcher
  (peak/half-peak/off-peak × summer/non-summer, `GET /matching/slots`). Full
  8760-hour matching and Taipower secondary (二次匹配) redistribution are future
  work (P4b).
```

- [ ] **Step 3: matching-rules.md 加章節**

於 `docs/matching-rules.md` 末尾加繁中章節(~200–300 字),說明:時段/季別定義、逐時段貪婪
`min(發電_slot, 用電_slot, 合約上限)`、合約 % 逐時段/月度能量跨時段共用、跨時段 RE、逐時段
灰電價的經濟意義。並加**專利對應**一段:實作專利式2/3/4(逐時段轉供量)、式5(T_slot≤G_slot)、
式6(跨時段 RE)、時間電價;沿用 P3 的 min_th/limit_gen、P2 的毛利;二次匹配與式7 留 P4b。
內容須與 `app/matching/slot_engine.py`、`app/matching/tou.py` 一致。

- [ ] **Step 4: 驗證 + Commit**

Run: `.venv/bin/python -m pytest -q`
```bash
git add README.md docs/matching-rules.md
git commit -m "docs(p4a): document time-slot TOU matching and patent alignment"
```

---

## 自審備註(writing-plans self-review)

- **Spec 覆蓋**:enum/tou(T1)、資料模型+migration(T2)、slot_engine(T3)、service+經濟+schema(T4)、
  API(T5)、產生器(T6)、儀表板(T7)、文件+專利對應(T8)——皆對應。
- **型別一致**:`match_slots` 簽章與回傳型別(`SlotMatchingOutcome` 及其欄位)在 T3 定義,
  T4 一致沿用;schema 欄位與 outcome 欄位逐一對映。
- **月度不動保護**:T2 明列既有測試回歸;T6 明測「月度引擎在時段資料上仍加總正確」。
- **determinism**:T3 測同/亂序輸入相同;`SLOT_ORDER` 固定序 + 穩定合約排序。
- **互斥不變式**:T6 產生器刪月度列、產時段列、尾差吸收,測試斷言加總=月度。
- **fixture**:沿用 `db` / `client`(對齊 `tests/integration/test_evaluation_api.py`)。
- **service 經濟計算**:T4 的 buyer 經濟為乾淨最終版(逐 allocation 綠電成本 + 逐時段灰電成本),無佔位/死碼。
