# 合約詳情頁（商務視角）Design

- **狀態**：Approved (design)
- **日期**：2026-07-31
- **一句話**：合約清單只講「紙上寫什麼」，這一頁講「實際跑成什麼樣」——每月拿到多少、被哪個約束卡住、三方的帳怎麼算。

---

## 1. 目標與觀眾

觀眾是**售電業（台智電）的商務窗口**，不是工程師。他們看完這一頁要能回答一句話：

> 這紙合約健不健康？該續、該加、還是該調？

主題順序因此固定為 **履約與風險 → 金額**。金額採**雙面帳**（買方帳／賣方帳／售電業毛利同框，明確標示哪一欄是給誰看的）。時間軸為**整年 12 個月**，可點入單月。

## 2. 已定決策

| 項目 | 決定 |
|---|---|
| 立場 | **雙面帳**——買方應付、賣方應收、售電業毛利同頁，分欄標示 |
| 時間軸 | **整年 12 個月**為主，點某月展開單月明細 |
| 頁面主題 | **履約與風險**優先，金額次之 |
| 資料來源 | 新增後端端點 `/analytics/contract-detail`，一次回傳整年 |
| 分配引擎 | **`match_period`（合約優先序）**——履約基準，非最佳化基準 |
| 風險告警 | **不進新端點**，前端另打既有 `/analytics/contract-risks` 過濾 |
| 示範資料 | **不動**。take-or-pay 在現行資料上不會觸發，照實顯示「未觸發」 |
| 引擎 | `app/matching/engine.py`、`contract_terms.py` **一行不改**，唯讀使用 |

## 3. 為什麼是 `match_period` 而不是 `optimize_period`

平台有兩套配置演算法，對「這紙合約拿到多少」給出不同數字：

- `match_period`（`app/matching/engine.py`）——依合約優先序逐紙分配，**會記錄綁定約束**
- `optimize_period`（`app/matching/optimizer.py`）——MILP 全域最佳化，**轉供結算單用的是這套**

履約講的是「依約該拿到什麼、實際拿到什麼」，不是「最佳化後會拿到什麼」，所以本頁一律以 `match_period` 為準。

**代價是本頁金額與轉供結算單頁對不起來。** 處理方式是主動揭露：④ 雙面帳區塊底部固定一行註記，寫明本頁為履約基準、結算單為最佳化基準，兩者數字會有落差。讓台智電自己發現對不上，比先講清楚糟得多。

為了讓差異**只剩引擎這一個變數**，金額公式逐字沿用 `settlement_service.py` 既有的那一套（見 §6），只是把作用範圍從「客戶」縮到「這紙合約」。

## 4. 架構

### 新增檔案

| 檔案 | 職責 |
|---|---|
| `app/services/contract_detail_service.py` | 唯一的新邏輯單元：跑 12 次引擎，抽出本合約的月度履約與金額 |
| `app/schemas/contract_detail.py` | 回應型別 |
| `tests/unit/test_contract_detail.py` | service 單元測試 |
| `tests/integration/test_contract_detail_api.py` | 端點測試 |

### 修改檔案

| 檔案 | 修改 |
|---|---|
| `app/api/v1/analytics.py` | 加一支 `GET /contract-detail` |
| `web/api.js` | 加 `contractDetail(contractId, year)` |
| `web/app.js` | 加 `renderContractDetail()`、路由 `contract`、清單列可點 |
| `web/styles.css` | 新區塊樣式 |

### 資料流

```
GET /analytics/contract-detail?contract_id=5&year=2024
  ↓
contract = contract_svc.get(db, contract_id)        # 不存在 → NotFoundError → 404
  ↓
for m in 1..12:
    outcome = compute_outcome(db, f"{year}-{m:02d}")     # 既有函式，不改
    a  = outcome.allocations 中 contract_id 相符者
    sk = a 為 None 時，從 outcome.skipped 找
    farm_unallocated  = outcome.farm_summaries 中本案場的 unallocated_mwh
    customer_unmet    = 本客戶的 consumption_mwh − allocated_mwh
  ↓
每月組出 ContractMonth（履約 + 金額）
  ↓
彙總 ContractYearTotals → ContractDetail
```

12 次引擎呼叫在示範規模（9 紙合約、6 案場、5 客戶、144 筆發電列）約為 24 次聚合查詢加 12 次純函式運算，不加快取。**真的變慢再說；現在加快取只會多一個會失效的地方。**

## 5. 綁定約束的分類

引擎的 `Allocation.reason` 已經記下綁定約束（`app/matching/engine.py` 的 `_reason()`），但那是給人讀的字串，且**可能同時列出多個**（例：`limited by wind farm supply, contract cap`）。本 service 負責把它變成可上色、可統計的結構：

```
binding: list[str]        # 可為多個，元素取值 contract_cap | farm_supply | customer_demand
binding_primary: str      # 單一值，供上色與統計
```

`binding_primary` 的優先序**固定為 `farm_supply` > `customer_demand` > `contract_cap`**。理由：若案場供給已用盡，那才是真正的限制——調高合約上限也拿不到更多電，合約上限同時綁定只是巧合。

其餘取值：

- `none`——本月生效但分配為 0（例如案場當月零發電）；`binding` 為空陣列
- `not_in_force`——合約該月未生效／已到期／狀態非 active（來自 `outcome.skipped`）；`binding` 為空陣列

### 商務結論句

頁面 ① 區的白話結論由 12 個月的 `binding_primary` 多數類別決定：

| 多數類別 | 結論句 |
|---|---|
| `contract_cap` | 「被合約上限卡住」，**若同時符合加購空間判定**再加「客戶的需求高於合約允許量，有加購空間」 |
| `farm_supply` | 「被案場供給卡住——此案場已無餘電可分配」，**兩個可選子句各有前提**（見下） |
| `customer_demand` | 「被客戶用電卡住——合約允許量高於客戶實際用得掉的量」 |
| `none` | 「該年度未取得任何分配」 |
| `not_in_force` | 「本合約於該年度未生效／已到期」 |

`farm_supply` 的兩個子句都必須有資料撐腰，否則略過：

- 「平均只拿到上限的 N%」——僅在 `totals.utilization_percent is not None` 時附加
- 「或本合約優先序（P）排在後面」——僅在 `higher_priority_sibling_count > 0` 時附加。這個欄位由 service 查出：**同一案場上、該年度內任一時點有效、且 `priority` 嚴格小於本合約**的合約數。若本合約已是該案場最高優先序，這句話就是錯的，不能寫。

### 加購空間判定（headroom）

`headroom` **僅在三個條件同時成立時**為 true：

1. `binding_primary == "contract_cap"`
2. `farm_unallocated_mwh > 0`（案場當月還有未分配電量）
3. `customer_unmet_mwh > 0`（客戶當月還有未滿足用電）

三者缺一即為 false，頁面只寫「被合約上限卡住」，不加後半句。`farm_unallocated_mwh` 與 `customer_unmet_mwh` 一併放進回應，讓這個判定**可被外部驗證、可被測試**，而不是頁面上一句無從查證的話。

## 6. 金額（雙面帳）

每月三方金額，公式沿用 `app/services/settlement_service.py` 既有那一套，作用範圍縮到單一合約。`kWh = MWh × 1000`。

```
售電價     = effective_price(合約 price_per_kwh, 漲幅%, 基準年, year)   # CPI 逐年複利
綠電費     = 分配量kWh × 售電價
輪供費     = 分配量kWh × settings.wheeling_fee_per_kwh
保證量差額 = max(0, 本月保證量門檻 − 分配量)
保證量費   = 保證量差額kWh × 售電價
──────────────────────────────────────────────
買方應付   = 綠電費 + 輪供費 + 保證量費
賣方應收   = 分配量kWh × 案場躉售價
售電業毛利 = 綠電費 − 賣方應收 − 輪供費 + 保證量費
碳減量     = 分配量MWh × settings.grid_emission_factor_kg_per_kwh   （tCO2e）
```

**不需要任何分攤假設**：所有費率都是 per-kWh，保證量門檻也是合約層級的（`min_offtake_mwh(monthly_volume_cap(...), min_offtake_percent)`），不必回答「這紙合約該分攤客戶多少費用」。

### 三個「不能假裝有值」的欄位

這個專案反覆栽在同一類錯誤上——標籤講了資料撐不住的話。以下三項寫進契約：

| 情況 | 行為 |
|---|---|
| 合約未設 `price_per_kwh` | `has_price = false`，**所有金額欄位為 `None`**。頁面隱藏整個 ④ 區並寫一行說明。不拿躉售價代入讓毛利變成 0 |
| 案場未設 `feed_in_price_per_kwh` | 採 `settings.default_feed_in_price_per_kwh`，並回傳 `used_default_feed_in = true`。頁面明寫「案場未設躉售價，採預設 N 元/度 試算」。給售電業看毛利卻不講成本是猜的，會出事 |
| 合約未設上限 | `cap_mwh = None` **且** `utilization_percent = None`。**null 不得變成 0，也不得變成 100**——「用掉 0%」與「沒有上限」是兩件事 |

### 不做的事

**不計算「履約健康度分數」。** 頁面頭部給的是事實：全年被什麼卡住、年度分配量、保證量差額、到期倒數、告警則數。把這些揉成一個 0–100 分等於發明一個資料撐不住的數字。

## 7. Schema（`app/schemas/contract_detail.py`）

```python
class ContractMonth(BaseModel):
    period: str                        # "2024-03"
    month: int                         # 1–12
    in_force: bool                     # False = 未生效／已到期／狀態非 active
    skip_reason: str | None            # 引擎原文，僅 in_force=False 時有值

    # 履約
    cap_mwh: float | None              # 本月合約上限（None = 未設上限，或該月未生效）
    cap_source: str                    # volume | percentage | both | none（依合約設了哪些
                                       # 上限欄位而定，12 個月皆同）
    allocated_mwh: float
    utilization_percent: float | None  # allocated/cap；cap 為 None 或 0 時亦為 None
    min_offtake_mwh: float             # take-or-pay 門檻（0 = 無此條款、非量制合約、或未生效）
    shortfall_mwh: float               # max(0, min_offtake_mwh − allocated_mwh)
    binding: list[str]
    binding_primary: str               # 見 §5
    reason: str                        # 引擎原文，可稽核
    headroom: bool                     # 見 §5
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
    binding_counts: dict[str, int]     # {"contract_cap": 12, ...}
    headroom_months: int
    energy_cost: float | None
    wheeling_fee: float | None
    take_or_pay_charge: float | None
    buyer_payable: float | None
    seller_receivable: float | None
    retailer_margin: float | None
    margin_percent: float | None       # 毛利 / 買方應付 × 100；買方應付為 0 時為 None
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
    monthly_share_fractions: list[float] | None   # 正規化後的 12 個占比，供繪圖
    min_offtake_percent: float | None
    price_escalation_percent: float | None
    price_base_year: int | None
    base_price_per_kwh: float | None
    higher_priority_sibling_count: int             # 見 §5 結論句

    # 計價前提（全部外顯，不藏預設值）
    has_price: bool
    used_default_feed_in: bool
    feed_in_price_per_kwh: float
    wheeling_fee_per_kwh: float
    grid_emission_factor_kg_per_kwh: float

    has_period_data: bool              # 該年度是否有任何發電或用電資料
    months: list[ContractMonth]        # 恆為 12 筆
    totals: ContractYearTotals
```

`monthly_share_fractions` 即使該年度未生效也會回傳——**條款本身就是資料**，月別配比的形狀不依賴有沒有實績。

## 8. 端點

```
GET /api/v1/analytics/contract-detail?contract_id={int}&year={int}
→ 200 ContractDetail
→ 404 合約不存在（contract_svc.get 拋 NotFoundError，既有 handler 映射）
```

`year` 必填，`ge=2000, le=2100`。放在 `/analytics` 下與 `settlement`、`contract-risks`、`meter-breakdown` 同慣例。唯讀，不掛 `require_write_access`。

Service 介面：

```python
def compute_contract_detail(db: Session, contract_id: int, year: int) -> ContractDetail
```

## 9. 前端

### 路由與進入點

`#/contract?id=5&year=2024`。年度預設取既有 `getPeriod()` 的前四碼（預設 `2024`，跨頁共用、存 localStorage）——不另發明一套期間狀態。

合約清單整列可點；編輯模式下點「操作」欄的按鈕不觸發跳頁。麵包屑「綠電合約 › PPA-2022-005」並附返回連結。

### 版面（由上而下）

**頁首**——合約編號、狀態徽章、`案場 → 客戶`、條款徽章（重用既有 `contractTerms()`）、右上年度選單。

**① 全年被什麼卡住**（主 KPI）——12 格分佈條，一格一月，依 `binding_primary` 上色：

| 取值 | 色 | 商務意義 |
|---|---|---|
| `contract_cap` | 藍 | 客戶要得比合約多 → 有加購空間（須通過 headroom 判定才這樣寫） |
| `farm_supply` | 橘 | 案場無餘電，或本合約優先序排在後面 |
| `customer_demand` | 灰綠 | 合約簽得比客戶用得掉的多 |
| `none` | 白（空心） | 生效但零分配（案場當月無發電） |
| `not_in_force` | 淺灰 | 未生效／已到期 |

下方一行由多數類別產生的結論句（見 §5）。次要數字：年度分配量、上限使用率、保證量差額、到期倒數、告警則數。

**② 月別履約圖**——12 根柱為實際分配（與 ① 同一套配色），實線為月上限，虛線為保證量門檻（無此條款不畫）。點某月展開該月明細，含引擎原文 `reason`。

**③ 風險告警**——打既有 `/analytics/contract-risks`，依 `contract_number` 過濾；無告警寫「目前無告警」。

**④ 雙面帳**——左買方（綠電費／輪供費／保證量費／應付合計），右賣方（案場應收），中間售電業毛利與毛利率，下方 12 列月別金額表。區塊底部固定註記履約基準與最佳化基準的差異（§3）。

**⑤ 合約條款**——起訖、優先序、上限、月別配比（12 格小條圖，未生效年度照畫）、take-or-pay（含「全年未觸發」）、CPI 年漲幅與逐年單價表。

## 10. 錯誤處理

| 情境 | 行為 |
|---|---|
| 合約不存在 | 404 → 沿用既有 `errbox()` |
| 該年度無發電／用電資料 | `has_period_data = false`；頁面不畫 ①②④，寫明「YYYY 年度尚無發電與用電資料」，**⑤ 條款照常顯示** |
| 合約該年度未生效／已到期 | 每月 `in_force = false`、灰格標「未生效」，**不是 0 MWh**。0 分配與「不該有分配」是兩件事 |
| 未設售電價 | ④ 整區隱藏 + 一行說明 |
| 案場未設躉售價 | ④ 加註「採預設 N 元/度 試算」 |
| 未設上限 | 不畫上限線；使用率顯示「未設上限」而非 0% |

## 11. 測試

### Python — `tests/unit/test_contract_detail.py`

- 回傳恆為 12 筆月份；月上限跟著 `monthly_shares` 走（非平均 1/12）
- `binding_primary` 四種分類正確，且多重綁定時依 §5 優先序取值
- **headroom 判定**：三條件齊備為 true；案場已無餘電的反例必須為 false
- 金額恆等式兩條：
  - `buyer_payable == energy_cost + wheeling_fee + take_or_pay_charge`
  - `retailer_margin == energy_cost − seller_receivable − wheeling_fee + take_or_pay_charge`
- **年度合計 == 12 個月加總**（本專案栽過 stock/flow 加總的跟頭，直接釘住）
- 未設上限 → `cap_mwh is None` **且** `utilization_percent is None`
- 未設售電價 → `has_price is False` 且所有金額欄位為 `None`
- 案場未設躉售價 → `used_default_feed_in is True`
- `in_force=False` 的月份不計入 `totals.allocated_mwh`
- CPI：`price_per_kwh` 隨年度複利，基準年之前不調
- `higher_priority_sibling_count`：同案場有更高優先序合約時 > 0；本合約已是該案場最高優先序時為 0（結論句因此不得出現優先序子句）
- `binding_primary` 為 `none` / `not_in_force` 時，`binding` 必為空陣列

### Python — `tests/integration/test_contract_detail_api.py`

- 正常路徑 200，`months` 長度 12
- 不存在的 `contract_id` → 404
- 無資料年度 → 200 且 `has_period_data is False`
- 對示範資料釘兩個事實：PPA-2024-004 全年 `binding_primary == "farm_supply"`；PPA-2022-005 `totals.shortfall_mwh == 0`

### 前端

`node --check web/app.js web/api.js`；Playwright 實際點入三紙代表性合約截圖驗證——**PPA-2022-005**（上限型）、**PPA-2024-004**（供給型）、**PPA-2025-008**（未生效型）——確認表格不溢出、無 console error、每個區塊都有值。

## 12. Gate

完整本地閘門：`ruff` · `black` · **`mypy app`** · `pytest` · `node --check`。SSH push。

## 13. 不在範圍內

- 從詳情頁編輯合約（清單頁的編輯模式已涵蓋）
- 合約全期（至 2033）的金額展望——示範資料只到 2024-12，展望等於拿假數字當真
- T-REC、逐時 CFE、儲能在合約層級的拆分
- 為此頁調整示範資料（take-or-pay 照實顯示未觸發）
- 快取或預先計算 12 個月的引擎結果
