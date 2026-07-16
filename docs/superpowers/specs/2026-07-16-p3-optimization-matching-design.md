# P3 經濟最佳化媒合設計

日期:2026-07-16
狀態:已核准方向,待實作
參考:微電能源_綠電匹配服務_v1.pdf(光電售電業媒合平台);承接 P1+P2
（`2026-07-16-green-power-retailer-evaluation-p1p2-design.md`）。

## 背景與目標

現有平台的媒合是 `app/matching/engine.py::match_period` —— **依 priority 逐一貪婪**
分配 `min(場剩餘, 客戶剩餘, 合約上限)`,deterministic、可稽核,是 README 門面。

P3 新增**經濟最佳化媒合**:不再由優先序決定,而是以**售電端毛利最大**為目標、在
**RE 目標**與兩個**結構約束**(最小分配%、最少案場數)下,對整個期間**全域求最優**
分配。以 MILP(混合整數線性規劃)求解,對齊參考 PDF 的真實產品做法。

方向決策(已拍板):
- 演算法:**MILP,用 PuLP + 內建 CBC**(純 Python、跨平台、CI 免額外安裝)。
- 目標:**最大化售電端總毛利**;客戶 RE 目標為**硬約束,不可行時退化為軟約束**
  (最小化缺口)。
- 整合:**新增獨立最佳化模式,與優先序引擎並存**;`match_period` 不動。

本 spec 只涵蓋 **P3**,維持**月度**、**compute-only**(不落地、不新增資料表)。明確排除
(留待後續):P4 時間電價/各時段、P5 轉供結算帳單、電號/契約容量。

## 架構總覽

```
app/matching/optimizer.py     # 純函式 MILP 求解(新增,不 I/O)
app/matching/engine.py        # 既有貪婪引擎(不動;僅其輸入 dataclass 加可選欄位)
app/services/optimize_service.py  # 從 DB 建輸入 → 跑 optimizer → 回結果(不落地)
app/schemas/optimization.py   # 請求選項 + 回應 schema
app/api/v1/matching.py        # 既有 router 加 GET /matching/optimize
app/core/config.py            # 加最佳化預設值
dashboard/pages/7_Optimization.py  # 選期間 + 調約束 + 並列對比優先序引擎
```

## 資料模型:輸入 dataclass 加可選欄位(向後相容)

最佳化需要**價格**與**RE 目標**,讓它們隨資料一起帶入。於 `app/matching/engine.py`
既有 frozen dataclass **加可選欄位、預設 `None`**;`match_period` 不讀這些欄位,行為與
既有測試完全不變。

| dataclass | 新欄位 | 型別 | 說明 |
|---|---|---|---|
| `FarmSupply` | `feed_in_price_per_kwh` | `float \| None = None` | 收購價;`None` → optimizer 回退 `settings.default_feed_in_price_per_kwh` |
| `ContractInput` | `price_per_kwh` | `float \| None = None` | 售電價;`None` → 該合約毛利率視為 0(price=feedin,不產生毛利也不虧) |
| `CustomerDemand` | `green_target_type` | `str \| None = None` | `"re_percent"` / `"energy"`;`None` → 視為 `re_percent` |
| `CustomerDemand` | `re_target_percent` | `float \| None = None` | type=re_percent 時的目標比例 |
| `CustomerDemand` | `target_energy_mwh` | `float \| None = None` | type=energy 時的目標綠電量(MWh) |

> 選擇「加欄位」而非「另傳 map」:資料與合約/場/客戶同體,optimizer 讀取語意清楚,
> 且不必在服務層維護平行對照表。

## MILP formulation(每期一次全域求解)

令**合格合約**集合 `E` = active 且在期間窗內的合約(資格判定沿用 engine `_is_eligible`)。
記 `farm(c)`、`cust(c)` 為合約 c 的風場/客戶;`generation[f]`、`consumption[k]` 為該期間
風場發電量、客戶用電量(MWh)。度數 = MWh × 1000(常數 `_KWH = 1000.0`)。

### 決策變數
- `alloc[c] ≥ 0`(連續,MWh),c ∈ E
- `use[c] ∈ {0, 1}`(二元:是否啟用該合約/案場),c ∈ E
- `re_short[k] ≥ 0`(連續,MWh):客戶 k 的 RE 缺口 slack
- `site_short[k] ≥ 0`(連續):客戶 k 的最少案場數缺口 slack

### 參數
- `cap[c]` = 合約上限,沿用 `engine._contract_limit(contract, generation[farm(c)])`;
  若為 `None`(無上限)→ `cap[c] = min(generation[farm(c)], consumption[cust(c)])`(自然上界)。
- `feedin[c]` = `farm(c).feed_in_price_per_kwh` 或 `settings.default_feed_in_price_per_kwh`。
- `price[c]` = `contract(c).price_per_kwh` 或 `feedin[c]`(缺價 → 毛利率 0)。
- `margin[c]` = `price[c] − feedin[c]`(NTD/kWh,可為負)。
- `re_target[k]` = RE 目標度數(MWh):
  - type=`re_percent`(或 None):`min(consumption[k], re_target_percent/100 × consumption[k])`
    ——`re_target_percent` 為 None 時視為 0。
  - type=`energy`:`min(consumption[k], target_energy_mwh)`——`target_energy_mwh` 為 None 時視為 0。
- `min_pct` = 最小分配%(選項,預設 `settings.optimize_min_site_allocation_percent`)。
- `min_sites[k]` = `min(設定的最少案場數, |{c ∈ E : cust(c)=k}|)`
  ——夾在該客戶合格合約數以內,避免不可能的下限。

### 目標(maximize)

為使懲罰階層**與資料尺度無關**(否則放大用電量時毛利項會蓋過「硬約束」懲罰,使 RE/
最少案場的硬性悄悄失效),先把毛利項**正規化到 [−1, 1]**:
```
MARGIN_UB = max(1.0, Σ_{c∈E} cap[c] × _KWH × max_{c∈E}|margin[c]|)
margin_term = ( Σ_{c∈E} alloc[c] × _KWH × margin[c] ) / MARGIN_UB      # ∈ [−1, 1]
```
求解目標:
```
maximize   margin_term
         − P_re   × Σ_k re_short[k]
         − P_site × Σ_k site_short[k]
         − ε      × Σ_{c∈E} use[c]
```
懲罰階層 `P_re ≫ P_site ≫ 1(margin_term) ≫ ε`,求解優先序:**先滿足 RE → 再滿足
最少案場 → 再毛利最大 → 最後 ε 破平局(傾向併案、可重現)**。實作常數(模組級):
- `P_re   = 1e6`(每 MWh RE 缺口;因 margin_term ≤ 1,任何缺口都優先消除 → 等效硬約束)
- `P_site = 1e3`(每 1 案場缺口;支配毛利、被 RE 支配)
- `ε      = 1e-6`(僅破平局,小於 margin_term 的有效解析度)

> 正規化後係數量綱固定於 `1e-6 … 1e6`,與 farms/客戶用電規模無關,CBC 數值穩定。
> **注意**:`margin_term` 只用於求解方向;對外回報的 `objective_gross_margin_ntd`
> 於求解後由分配另行計算(= Σ alloc×1000×margin,未正規化、不含懲罰),語意不受影響。

### 約束
1. 場供給:`∀f: Σ_{c∈E, farm(c)=f} alloc[c] ≤ generation[f]`
2. 客戶需求:`∀k: Σ_{c∈E, cust(c)=k} alloc[c] ≤ consumption[k]`
3. 合約上限 / 啟用連結:`∀c: alloc[c] ≤ cap[c] × use[c]`
   (use=0 ⇒ alloc=0;use=1 ⇒ alloc ≤ cap)
4. 最小分配%(硬,恆可行——solver 可令 use=0):
   `∀c: alloc[c] ≥ (min_pct/100 × consumption[cust(c)]) × use[c]`
5. 最少案場數(軟):`∀k: Σ_{c∈E, cust(c)=k} use[c] + site_short[k] ≥ min_sites[k]`
6. RE 目標(硬約束→軟化):`∀k: Σ_{c∈E, cust(c)=k} alloc[c] + re_short[k] ≥ re_target[k]`

> **為何 RE 與最少案場用 slack 而非純硬約束**:純硬約束在供給/合約不足時會讓整個
> MILP infeasible、無解可回。slack + 大懲罰使模型**恆可行**,且「可行時等同硬約束、
> 不可行時自動最小化缺口」,正是拍板的「硬約束,不可行退軟」語意,一次求解達成。
> 最小分配% 走 use 開關,天生恆可行,故用硬約束。

## Determinism(可重現性)

MILP 最優解可能非唯一。策略:
- 建模時合約以穩定序 `(priority, start_date, contract_number)` 逐一加入。
- 求解用 `PULP_CBC_CMD(threads=1, msg=0)`(單執行緒、關 log)。
- 目標含 `− ε·Σ use[c]` 破平局(毛利相同時傾向較少案場,收斂唯一解)。

驗收:同一輸入求解兩次、以及把輸入 list 打亂順序後求解,`alloc` 逐筆相同(四捨五入
6 位後比較)。

## 輸出

`optimizer.optimize_period(...)` 回傳 `OptimizationOutcome`,**繼承** engine 的
`MatchingOutcome`(沿用 `allocations` / `skipped` / `customer_summaries` /
`farm_summaries` 與其彙總 property),額外加:

| 欄位 | 型別 | 說明 |
|---|---|---|
| `solver_status` | `str` | CBC 狀態字串(如 `"Optimal"`) |
| `objective_gross_margin_ntd` | `float` | 售電端總毛利(NTD),= Σ alloc×1000×margin(**不含 slack 懲罰**) |
| `customer_targets` | `list[CustomerTarget]` | 每客戶:`customer_id`、`re_target_mwh`、`allocated_mwh`、`re_shortfall_mwh`、`re_target_met: bool`、`sites_used: int`、`site_shortfall: int` |

- `allocations`:每筆合格合約一筆,`allocated_mwh` = 求解後四捨五入 6 位;`reason` 標記
  綁定約束(沿用 `engine._reason` 的判定:場供給 / 客戶需求 / 合約上限;alloc=0 且
  合格 → `"optimizer 未選用"`;RE 樓地板綁定時併記)。`contract_limit_mwh` = `cap[c]`。
- `skipped`:不合格合約,reason 沿用 `_is_eligible`。
- `customer_summaries` / `farm_summaries`:比照 engine 由分配加總計算(重用相同計算,
  抽為共用 helper,避免重複邏輯)。

### CustomerTarget dataclass(optimizer.py)
```python
@dataclass
class CustomerTarget:
    customer_id: int
    re_target_mwh: float
    allocated_mwh: float
    re_shortfall_mwh: float
    re_target_met: bool          # re_shortfall_mwh <= _EPS
    sites_used: int
    site_shortfall: int
```

## 服務層

`app/services/optimize_service.py`:
- `OptimizeOptions`(dataclass):`min_sites_per_customer: int`、
  `min_site_allocation_percent: float`(未給則於 API 層以 config 預設填入)。
- `compute_optimized(db, period, options) -> OptimizationOutcome`:比照
  `matching_service.compute_outcome` 從 DB 撈該期間 farms/customers/contracts/generation/
  consumption,組成加了新欄位的 dataclass,呼叫 `optimize_period`,**不落地**。
- 期間邊界重用 `matching_service.period_bounds(period)`。

## API

於既有 `app/api/v1/matching.py` 加:
```
GET /api/v1/matching/optimize
    ?period=YYYY-MM                       (必要)
    &min_sites=<int>                      (可選,預設 settings.optimize_min_sites_per_customer)
    &min_site_allocation_percent=<float>  (可選,預設 settings.optimize_min_site_allocation_percent)
→ 200 OptimizationResult
```
- 回應 schema `app/schemas/optimization.py::OptimizationResult`:
  - `period`、`solver_status`、`objective_gross_margin_ntd`
  - `allocations: list[AllocationOut]`(沿用/比照既有 matching result 欄位)
  - `customer_targets: list[CustomerTargetOut]`
  - `farm_summaries` / `customer_summaries`(比照既有 analytics 結構)
- period 格式非法 → 422(沿用既有驗證);該期間無資料 → 200 空結果(各 0,不報錯)。

## 設定 `app/core/config.py`

| 設定 | 預設 | 說明 |
|---|---|---|
| `optimize_min_sites_per_customer` | `0` | 每客戶最少案場數下限預設(0=不限) |
| `optimize_min_site_allocation_percent` | `0.0` | 最小分配%預設(0=不限);定義為**佔該客戶用電量的百分比** |

預設皆為關閉,不影響任何既有行為。

## 儀表板 `dashboard/pages/7_Optimization.py`

- 選期間;拉桿調 `最少案場數`、`最小分配%`。
- 顯示最佳化結果:每客戶 RE 達成(達標旗標 / 缺口)、售電端總毛利、各筆分配(含 reason)。
- **並列對比**:同期間同時呼叫既有優先序媒合(`POST /matching/runs` 或既有 analytics)
  與最佳化,並排顯示**總毛利**與**平均 RE%**,凸顯兩種策略差異(P3 賣點)。
- `dashboard/api_client.py` 加 `optimize(period, min_sites, min_site_allocation_percent)`。

## 相依

`pyproject.toml` 核心相依加 `pulp`(純 Python;內建 CBC binary,跨平台免額外安裝,
CI 可直接執行)。

## 邊界與決策

- 無合格合約 / 無用電 → `alloc` 全 0、毛利 0、各客戶 re_target_met 依 target 是否為 0
  判定(target=0 → met=True),不報錯。
- `margin[c] < 0`(售電價低於收購價):optimizer 除非為滿足 RE/最少案場,否則不會主動
  分配(因降低目標);若為達 RE 硬約束需要,仍可能分配(RE 懲罰更大)——符合「先達標」。
- `min_pct` 使某合約 `min_pct/100×consumption > cap[c]` → 該合約永遠 use=0(太小無法達
  樓地板而被排除),合理。
- 求解狀態非 `Optimal`(理論上因恆可行不應發生)→ 回應帶 `solver_status`,分配以求得值
  輸出;測試涵蓋恆可行性。

## 測試策略

單元 `tests/unit/test_optimizer.py`:
- 高毛利場優先:2 場 1 客戶、供給皆足,optimizer 全給高 margin 場;斷言分配與
  `objective_gross_margin_ntd`。
- RE 硬約束:供給足時 `re_target_met=True` 且 `allocated ≥ re_target`;供給不足時
  `re_shortfall_mwh > 0` 且 met=False。
- 最少案場數:`min_sites=2` 且有 ≥2 可用場 → 分配跨 ≥2 場(`sites_used ≥ 2`);僅 1 場
  可用 → `site_shortfall > 0` 但仍求解。
- 最小分配%:設 `min_pct` 使小場達不到樓地板 → 該小場 `use=0`、alloc=0。
- determinism:同輸入兩次相同;打亂 contracts 順序後相同。
- optimizer 不劣於 greedy:同輸入下 `objective_gross_margin_ntd` ≥ 以 engine 結果算得的
  毛利(全域最優不劣於貪婪)。
- 邊界:空合約 / 空用電不崩,回全 0。

整合 `tests/integration/test_optimize_api.py`:
- seed → `GET /matching/optimize?period=...` → 200 + 完整結構(含 customer_targets、
  objective)。
- 帶 `min_sites` / `min_site_allocation_percent` query → 反映於結果。
- 無資料期間 → 200 空結果。

CI:pulp 內建 CBC 於 GitHub Actions 直接可執行,無需額外安裝步驟。

## 文件

- `docs/matching-rules.md`:新增 optimizer 章節(目標、約束、slack 語意、determinism)。
- `README.md`:「Known limitations」把「Greedy priority allocation, not a global optimum」
  改為「兩種可選媒合策略:優先序(deterministic)/ 全域經濟最佳化(MILP)」;API 表加
  `GET /api/v1/matching/optimize`。

## 後續階段(不在本 spec)

P4 時間電價/各時段、P5 轉供結算帳單、電號/契約容量管理。
