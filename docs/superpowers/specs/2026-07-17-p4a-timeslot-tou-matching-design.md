# P4a 時段時間電價媒合設計

日期:2026-07-17
狀態:已核准方向,待實作
參考:微電能源綠電匹配專利(案號 113147880);承接 P1/P2/P3。

## 背景與目標

現有平台媒合為**月度**粒度(`match_period` 貪婪、P3 MILP 最佳化)。本階段把媒合細化到
**台電三段式時間電價**時段(尖峰/半尖峰/離峰 × 夏月/非夏月),逐時段做**物理媒合**並算
**時段別經濟**,對齊參考專利的時段模型:

- 式2/3/4:轉供量 = min(發電分配, 用電分配);逐時段版。
- 式5:任一時段轉供量 `T_slot ≤ G_slot`(該時段發電分配量)。
- 式6:`RE = 總轉供量 / 總用電量`,跨時段加總。
- 時間電價:發用電量與灰電價逐時段不同。

方向決策(已拍板):
- **P4a 只做三段式 TOU 逐時段貪婪媒合 + 時段別經濟**;台電**二次匹配**、式7 最小化餘電
  目標式、逐時段綠電計價、逐時段 MILP **留 P4b**。
- **新增時段媒合路徑,月度引擎/優先序/P3 MILP 全部不動(並存)**。
- 逐時段 demo 資料由**deterministic 產生器**把月度量依風電典型時段占比拆出。

## 架構總覽

```
app/models/enums.py            # 新增 TimeSlot、Season enum
app/models/generation.py       # GenerationData 加 time_slot(可空)
app/models/consumption.py      # ConsumptionData 加 time_slot(可空)
alembic/versions/...           # 一支 migration(兩表加 time_slot)
app/matching/tou.py            # 時段/季別工具 + TOU 灰電參考價
app/matching/slot_engine.py    # 純函式逐時段媒合(月度引擎不動)
app/services/slot_matching_service.py  # 從 DB 建輸入 → 媒合 → 時段經濟 → schema(不落地)
app/schemas/slot_matching.py   # 回應 schema
app/api/v1/matching.py         # 加 GET /matching/slots
scripts/generate_slot_profiles.py  # 月度 → 時段 profile 產生器
dashboard/pages/8_時段媒合.py  # 時段別發用電/RE/毛利
dashboard/api_client.py        # 加 slot_matching(period)
```

## 時段與季別模型

`app/models/enums.py` 新增:

```python
class TimeSlot(StrEnum):
    PEAK = "peak"            # 尖峰
    HALF_PEAK = "half_peak"  # 半尖峰
    OFF_PEAK = "off_peak"    # 離峰


class Season(StrEnum):
    SUMMER = "summer"        # 夏月
    NON_SUMMER = "non_summer"  # 非夏月
```

季別由月份推導(不存欄位)。台電夏月 = 6/1–9/30:

```python
def season_of(month: int) -> Season:
    return Season.SUMMER if 6 <= month <= 9 else Season.NON_SUMMER
```

`SLOT_ORDER = (TimeSlot.PEAK, TimeSlot.HALF_PEAK, TimeSlot.OFF_PEAK)` — 固定時段處理序,
確保 determinism 且讓高價尖峰時段優先取用合約月度電量預算。

## 資料模型(向後相容)

`GenerationData`、`ConsumptionData` 各加一欄:

| 欄位 | 型別 | 說明 |
|---|---|---|
| `time_slot` | `TimeSlot \| None`(nullable) | `None` = 月度彙總列(舊資料);否則為該時段列 |

- **互斥規則**:同一 `(案場/客戶, 月)` 只能有「月度單列(`time_slot=None`)」**或**「時段多列
  (尖/半/離)」其一;時段列的能量**加總 = 月度總量**。
- **月度引擎不受影響**:`matching_service._sum_generation` / `_sum_consumption` 對該月**所有**
  列加總 → 若為時段列則自動加回月度總量,`match_period` / 優先序 / P3 MILP 全部照常。
- Alembic migration:兩表各 `add_column('time_slot', nullable=True)`;`alembic upgrade head`
  後既有測試全綠(欄位可空、預設 None)。
- Schema:`GenerationData` / `ConsumptionData` 的 Pydantic read/create 加可選 `time_slot`;
  CSV importer 讀可選 `time_slot` 欄(空 → None)。

## 時間電價(TOU 灰電參考價)

`app/matching/tou.py` 提供 (季, 時段) → 灰電價(NTD/kWh)參考表(demo 值,可由設定覆寫):

```python
# 示意值(NTD/kWh),對齊台電高壓時間電價量級;僅供 demo,實務可調
GREY_TOU_PRICES: dict[tuple[Season, TimeSlot], float] = {
    (Season.SUMMER,     TimeSlot.PEAK):      5.0,
    (Season.SUMMER,     TimeSlot.HALF_PEAK): 3.5,
    (Season.SUMMER,     TimeSlot.OFF_PEAK):  1.8,
    (Season.NON_SUMMER, TimeSlot.PEAK):      4.7,
    (Season.NON_SUMMER, TimeSlot.HALF_PEAK): 3.4,
    (Season.NON_SUMMER, TimeSlot.OFF_PEAK):  1.7,
}


def grey_price(season: Season, slot: TimeSlot) -> float:
    return GREY_TOU_PRICES[(season, slot)]
```

- **綠電轉供價**:P4a 沿用合約 `price_per_kwh`(單一費率,PPA 常態),**不**逐時段。TOU 的
  經濟價值透過**灰電價逐時段不同**體現(尖峰灰電貴 → 尖峰供的綠電對用電端更有價值/省更多)。
- **收購價(FIT)**:沿用 `farm.feed_in_price_per_kwh` 或 `settings.default_feed_in_price_per_kwh`。
- 逐時段綠電計價列為 P4b/後續可選擴充。

## 逐時段媒合引擎(月度不動)

`app/matching/slot_engine.py` 為純函式,不 I/O、deterministic。

### 輸入 dataclass
```python
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
```
合約沿用 `app.matching.engine.ContractInput`(已含 `price_per_kwh`)。

### 輸出 dataclass
```python
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
class SlotCustomerSummary:   # 跨時段加總(式6)
    customer_id: int
    consumption_mwh: float
    allocated_mwh: float
    achieved_re_percent: float

@dataclass
class SlotFarmSummary:       # 跨時段加總
    farm_id: int
    generated_mwh: float
    allocated_mwh: float
    unallocated_mwh: float

@dataclass
class SlotMatchingOutcome:
    period: str
    season: Season
    allocations: list[SlotAllocation]          # 逐 (合約, 時段)
    skipped: list[SkippedContract]             # 沿用 engine
    customer_summaries: list[SlotCustomerSummary]
    farm_summaries: list[SlotFarmSummary]
    # 逐時段小計(供儀表板時段別檢視)
    slot_customer_summaries: list[tuple[TimeSlot, SlotCustomerSummary]]
    slot_farm_summaries: list[tuple[TimeSlot, SlotFarmSummary]]
```

### 函式
```python
def match_slots(
    period: str,
    period_start: date,
    period_end: date,
    farms: list[SlotFarmSupply],
    demands: list[SlotCustomerDemand],
    contracts: list[ContractInput],
) -> SlotMatchingOutcome
```

### 演算法
`season = season_of(period_start.month)`(整月同一季)。合約先過 `engine._is_eligible`
(不合格 → skipped);合格合約以 `(priority, start_date, contract_number)` 穩定排序。

對每個合約維護**月度能量預算** `remaining_energy = contracted_energy_mwh`(若為 None 則無此
上限)。逐時段(依 `SLOT_ORDER`)、逐合約分配:

```
for slot in SLOT_ORDER:
    farm_gen_slot   = generation[(farm, slot)]
    for contract in ordered_eligible:
        farm_rem   = farm_slot_remaining[(farm, slot)]
        cust_rem   = consumption[(cust, slot)] - allocated_to_cust_slot[(cust, slot)]
        pct_cap    = (contracted_percentage/100 × farm_gen_slot) if contracted_percentage else +inf
        energy_cap = remaining_energy[contract] if contracted_energy_mwh else +inf
        alloc = round(min(max(0, farm_rem), max(0, cust_rem), pct_cap, energy_cap), 6)
        # 記錄 SlotAllocation + reason(綁定:場供給/客戶需求/合約%上限/合約月度能量)
        # 扣減 farm_slot_remaining、allocated_to_cust_slot、remaining_energy[contract]
```

- **式5** 由「每時段 `alloc ≤ farm_rem`(該時段發電)」保證。
- **合約 % 上限**逐時段以該時段發電量計(式3 精神);**合約月度能量上限**為跨時段共用預算
  (尖峰時段先取用,符合高價優先)。
- 每時段每合約一筆 `SlotAllocation`(含 alloc=0);reason 沿用 `engine._reason` 精神標記綁定。

### 彙總
- 逐時段小計:每 (時段) 對每客戶/案場用 `engine.build_customer_summary` / `build_farm_summary`
  產生時段小計。
- 跨時段客戶/案場 summary(式6 的 RE 跨時段加總):對每客戶加總各時段 allocated 與 consumption,
  再算 `achieved_re_percent`;案場同理。

> **重用而非重寫**:資格判定、合約上限、reason、summary helper 皆重用 `engine` 既有函式。

## 服務層

`app/services/slot_matching_service.py`:
- `compute_slot_outcome(db, period) -> SlotMatchingResult`(schema),**compute-only**(不落地)。
- 從 DB 撈該月**時段列**(`time_slot IS NOT NULL`)組 `SlotFarmSupply`/`SlotCustomerDemand`;
  合約沿用 `matching_service.compute_outcome` 的合約建構方式(含 `price_per_kwh`)。
- 期間邊界重用 `matching_service.period_bounds`。
- **時段別經濟**(此層計算,對齊 P2):
  - 售電端毛利(逐時段加總):`Σ_slot Σ_alloc allocated_kwh × (contract.price_per_kwh − feedin)`
  - 用電端:RE% 跨時段;**均價/增加成本用逐時段灰電價** `tou.grey_price(season, slot)`:
    - 增加用電成本 = `Σ_slot Σ_alloc allocated_kwh × (contract.price_per_kwh − grey_price(season, slot))`
  - 度數 = MWh × 1000。

## API

於既有 `app/api/v1/matching.py` 加:
```
GET /api/v1/matching/slots?period=YYYY-MM  → 200 SlotMatchingResult
```
`app/schemas/slot_matching.py::SlotMatchingResult`:
- `period`、`season`
- `allocations`(逐時段)、`customer_summaries`(跨時段)、`farm_summaries`(跨時段)
- `slot_breakdown`:逐時段的 {slot, 客戶/案場小計, 灰電價}
- `seller_gross_margin_ntd`、`buyer`(re_percent / avg_price / added_cost)
- 無時段資料的期間 → 200 空結果(各 0)。

## 時段 profile 產生器

`scripts/generate_slot_profiles.py`:deterministic,把每筆**月度** gen/consumption 依時段占比
拆成尖/半/離三列(`time_slot` 非空),加總=月度總量。占比(設定,風電典型):

| | 尖峰 | 半尖峰 | 離峰 |
|---|---|---|---|
| 發電(風電,夜間/離峰較高) | 0.25 | 0.30 | 0.45 |
| 用電(工業,日間/尖峰較高) | 0.40 | 0.35 | 0.25 |

- CLI:`python -m scripts.generate_slot_profiles`(對現有月度 demo 就地拆時段;冪等)。
- 為維持互斥規則:產生時段列時**移除/取代**同 (實體, 月) 的月度列(或於乾淨 seed 上直接產時段列)。
- 尾差用最後一個時段吸收,確保加總嚴格等於月度總量(避免捨入漂移)。

## 測試策略

單元 `tests/unit/test_slot_engine.py`:
- 逐時段貪婪:單場單客戶三時段,斷言各時段 `alloc = min(發電_slot, 用電_slot, 上限)`。
- 式5:任一時段 alloc ≤ 該時段發電。
- 合約 % 上限逐時段;合約月度能量上限為跨時段共用預算(尖峰先取用,總和不超月度上限)。
- 跨時段 RE(式6):Σ轉供/Σ用電。
- determinism:同輸入 / 打亂 farms·demands·contracts 順序 → 完全相同分配。
- 不合格合約 skipped;空輸入不崩。

單元 `tests/unit/test_tou.py`:`season_of` 邊界(5/6/9/10 月)、`grey_price` 對照。

單元 `tests/unit/test_slot_profiles.py`:產生器輸出**加總=月度**、占比正確、deterministic。

整合 `tests/integration/test_slot_matching_api.py`:seed 月度 → 產生時段 → `GET /matching/slots`
→ 200 + 時段結構;**同時驗證月度引擎在時段資料上仍正確**(`compute_outcome` 加總回月度總量)。

migration:`alembic upgrade head` 後 `time_slot` 欄存在;既有測試全綠。

## 邊界與決策
- 某時段無發電或無用電 → 該時段 alloc 0,不報錯。
- 合約 `contracted_energy_mwh` 為月度上限,跨三時段共用;`contracted_percentage` 逐時段計。
- 灰電 TOU 價僅影響**用電端經濟**(均價/增加成本);售電端毛利用綠電轉供價(單一費率)。
- 時段列與月度列互斥;產生器負責維持此不變式。

## 專利對應(claim 元素)
- **本階段實作**:式2/3/4(逐時段轉供量 = min(發電分配, 用電分配))、**式5**(`T_slot ≤ G_slot`)、
  **式6**(跨時段 RE = 總轉供/總用電)、**時間電價**(逐時段灰電價)。
- **沿用 P3**:`min_th` = `min_site_allocation_percent`、`limit_gen` = `min_sites_per_customer`。
- **沿用 P2**:收益/毛利(式8 精神:轉供收入 − 收購成本)。

## 後續階段(不在本 spec)
- **P4b**:台電**二次匹配**(同時段餘電池化再分配)、**式7 最小化餘電**目標式、逐時段
  MILP 最佳化(把 P3 擴到時段)、逐時段綠電轉供計價。
- P5 轉供結算帳單;電號/契約容量(多電號 aggregate RE,對應專利雙廠區實例)。
