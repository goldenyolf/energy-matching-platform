# P4b 逐時段 MILP 最佳化(二次匹配)設計

日期:2026-07-18
狀態:已核准方向,待實作
參考:微電能源綠電匹配專利(案號 113147880)式5/式7;承接 P3/P4a/v1.1。

## 背景與目標

v1.1 統一端點目前用**月度 P3 MILP**求解,再把結果**依時段發電占比推估**到時段(離峰過剩
變「錯配餘電」)。P4b 用**真實逐時段最佳化**取代推估:對某期間三時段(尖/半/離)做**聯合
MILP**,對齊專利:
- **式5**:逐時段轉供 ≤ 該時段發電、≤ 該時段用電。
- **式7 目標**:滿足 RE 下**最小化總發電分配量**(釋出剩餘可分配發電/減少低效分配)。
- **台電二次匹配**:每時段全域最佳化,自然把同時段「供過於求」配對的餘電移到「不足」配對。

結果:時段面板 = **最優、精確值**(逐時段式5 上限 → RE 天生 ≤ 100%,無推估餘電欄);
economics/逐案場 = 逐時段分配加總 → 與時段面板**完全一致**。

方向決策(已拍板):**單期間**逐時段聯合 MILP、目標**式7 最小化分配**、**無資料模型變更**;
統一端點改用它;月度 `/matching/optimize`、`/matching/slots`、evaluation **不動**。

## 核心:聯合逐時段 MILP `app/matching/slot_optimizer.py`

RE 目標是**跨時段加總**,故三時段須放進**同一個** MILP(非三個獨立)。純函式、
deterministic(`PULP_CBC_CMD(msg=0, threads=1)` + 穩定合約序 + ε 破平局)。

### 輸入
- `SlotFarmSupply(farm_id, slot, generated_mwh)`、`SlotCustomerDemand(customer_id, slot, consumed_mwh)`
  (沿用 `slot_engine`);合約沿用 `ContractInput`(含 `price_per_kwh`)。
- `SlotOptimizeOptions`:`min_sites_per_customer`、`min_site_allocation_percent`、
  `re_target_percent_override: dict[int,float] | None`(每客戶目標覆寫)、
  `default_feed_in_price_per_kwh`。
- RE 目標由 `CustomerDemand.green_target_type/re_target_percent/target_energy_mwh` 帶(比照 P3),
  或由覆寫 dict 取代。

### 變數(合格合約 c、時段 s∈{peak,half,off})
- `alloc[c,s] ≥ 0`(MWh)
- `use[c] ∈ {0,1}`(該合約是否啟用,跨時段)
- `re_short[k] ≥ 0`、`site_short[k] ≥ 0`(每客戶 slack)

### 參數
- `gen[f,s]`、`con[k,s]`(逐時段)。`feedin[c]`、`price[c]`、`re_target[k]`(度數 = MWh×1000):
  比照 P3;`re_target[k] = min(Σ_s con[k,s], target)`。
- `slot_cap[c,s]`:`contracted_percentage`→`pct/100×gen[farm(c),s]`;無則 `min(gen[farm(c),s], con[cust(c),s])`。
- `energy_cap[c]`:`contracted_energy_mwh`(跨時段共用)。
- `use_cap[c] = Σ_s slot_cap[c,s]`(與 energy_cap 取小,作 use 連結上界)。

### 約束
1. **式5 場供給**:∀f,s:`Σ_{c∈f} alloc[c,s] ≤ gen[f,s]`
2. **式5 客戶需求**:∀k,s:`Σ_{c∈k} alloc[c,s] ≤ con[k,s]`
3. **時段%上限**:∀c,s:`alloc[c,s] ≤ slot_cap[c,s]`
4. **月度能量上限**:∀c:`Σ_s alloc[c,s] ≤ energy_cap[c]`(若有)
5. **use 連結 + 最小分配%**:∀c:`Σ_s alloc[c,s] ≤ use_cap[c]·use[c]`;
   `Σ_s alloc[c,s] ≥ max(min_pct/100×con_total[cust(c)], _EPSILON)·use[c]`
6. **最少案場數(軟)**:∀k:`Σ_{c∈k} use[c] + site_short[k] ≥ min(min_sites, |c∈k|)`
7. **RE 硬約束(軟化,跨時段)**:∀k:`Σ_s Σ_{c∈k} alloc[c,s] + re_short[k] ≥ re_target[k]`

### 目標(minimize,式7)
```
minimize  Σ_{c,s} alloc[c,s]·_KWH
        + P_re   × Σ_k re_short[k]·_KWH
        + P_site × Σ_k site_short[k]
        + ε      × Σ_c use[c]
```
懲罰階層 `P_re(1e6) ≫ P_site(1e3) ≫ 分配項 ≫ ε(1e-6)`:**先滿足 RE → 再滿足最少案場 →
再最小化分配(式7)→ ε 破平局(傾向少案場,對齊專利去低效)**。度數量綱一致(alloc/re_short ×_KWH)。

### 輸出 `SlotOptimizationOutcome`
- `solver_status`、`allocations: list[{contract_id, contract_number, wind_farm_id, customer_id, slot, allocated_mwh, reason}]`(逐時段)
- `customer_slot`:每 (客戶,時段) 的 consumption/allocated/re_percent
- `customer_totals`:每客戶跨時段 consumption/allocated/re_percent/re_shortfall_mwh/sites_used/site_shortfall
- `farm_totals`:每風場跨時段 generated/allocated

> 二次匹配:約束1(逐時段場供給)+ 全域最小化,使同時段餘電在客戶間最優再分配。

## 整合:統一端點改用逐時段 MILP

`app/services/customer_optimization_service.py::compute_customer_optimization` 改為:
1. 從 DB 撈該期間**時段列**(`time_slot IS NOT NULL`)組 `SlotFarmSupply`/`SlotCustomerDemand`
   (若無時段資料 → 回退月度 P3,標記 `fallback_monthly=True`,維持相容)。
2. 若 `re_target_percent` 覆寫 → 放進 `re_target_percent_override[customer_id]`。
3. 跑 `slot_optimizer.optimize_slots(...)`;取 focus 客戶的逐時段分配。
4. **economics 由逐時段分配加總算**(比照現行:green_kwh/procurement/revenue;`transfer_price` 覆寫仍適用)。
5. **slot_breakdown = focus 客戶的 customer_slot**(最優、精確;`re_percent ≤ 100%` 天生成立)。
6. `time_mismatch_surplus_mwh` 改為**真實值** = `re_target_mwh − allocated_mwh`(因逐時段式5 上限無法達標的缺口;達標則 0)。
7. 逐案場 = focus 客戶逐時段分配依 farm 加總。

回應 schema `CustomerOptimizationResult` **欄位不變**(前端不用改);僅 `slot_breakdown` 與
`time_mismatch_surplus_mwh` 語意從「推估」變「最優精確」。SPA 的 slotnote 文案微調
(「依占比推估」→「逐時段最佳化」)。

## 測試策略

單元 `tests/unit/test_slot_optimizer.py`:
- **式5**:任一時段 `Σalloc ≤ gen` 且 `≤ con`。
- **RE 可行達標 / 不可行 re_short**(尤其離峰過剩無法於離峰媒合 → re_short>0)。
- **式7 最小化**:RE 目標 50%、供給充足 → 分配剛好達 50%(不過度)。
- **二次匹配**:兩客戶共用一場、同時段一方過剩一方不足 → 餘電移轉、總 RE 最大。
- `min_th` 排除碎屑、`min_sites` 強制分散;determinism(同/亂序輸入相同)。
- 空輸入、solver Optimal。

整合 `tests/integration/test_customer_optimization.py`(擴充):
- **一致性**:`buyer.green_mwh == Σ slot allocated == Σ farm allocated`;各 slot `re_percent ≤ 100%`。
- 覆寫 `re_target_percent` / `transfer_price` 仍生效。
- 無時段資料期間 → 回退月度、不崩。
- API `test_customer_optimization_api`:結構不變、值反映。

## 邊界與決策
- RE 目標跨時段加總;逐時段式5 上限使離峰過剩綠電無法灌到離峰 → 反映為 re_short(真實時段錯配)。
- min_th/limit_gen 作用於**跨時段聚合**(use[c] 為合約是否啟用;min_pct 佔客戶總用電%)。
- 無時段資料 → 回退月度 P3(相容,不強制先跑 generate_slot_profiles)。
- 保留 `slot_engine`(P4a 貪婪)、月度 `optimize_period`(P3);P4b 為新增。

## 後續(不在本 spec)
- 多期間計費周期二次匹配(同時段餘電跨月池化);P5 轉供結算;投資效益 ROI/回收期。
