# 綠電售電業評估(P1+P2)設計

日期:2026-07-16
狀態:已核准方向,待實作
參考:微電能源_綠電匹配服務_v1.pdf(光電售電業媒合平台)

## 背景與目標

現有平台是「風力綠電媒合 MVP」:風場/客戶/合約/月度發用電 + 優先序媒合 + RE% 分析。
目標是往參考 PDF 的**售電業決策工具**演進 —— 媒合後產出**雙面經濟評估**(售電端毛利
+ 用電端 RE%/成本)。

本 spec 只涵蓋 **P1(資料模型對齊)+ P2(售電評估)**,維持**月度**粒度。明確排除
(留待後續階段):P3 最佳化媒合、P4 時間電價/各時段、P5 轉供結算帳單、電號/契約容量。

方向決策(已拍板):售電業雙面經濟視角、先維持月度、從 P1+P2 起步。

## P1 — 資料模型對齊

皆為 SQLAlchemy 模型變更,需 Alembic migration;CSV importer 以**可選欄位**讀取,舊資料
與樣本向後相容。

### 發電端 `app/models/wind_farm.py`

| 欄位 | 型別 | 說明 |
|---|---|---|
| `feed_in_price_per_kwh` | `float \| None` | 躉售/收購價(NTD/kWh),算收購成本;None → 用設定的預設值 |

- 台電真實風場(`TPC-`)無價格資料 → 匯入時留 `None`,評估時回退 `settings.default_feed_in_price_per_kwh`。
- Schema:`WindFarmBase` 加欄位;`WindFarmCreate` 沿用;importer 讀 `feed_in_price_per_kwh`(可空)。

### 用電端 `app/models/customer.py`

| 欄位 | 型別 | 說明 |
|---|---|---|
| `green_target_type` | Enum `GreenTargetType`{`re_percent`,`energy`} | 對齊 PDF「目標RE比例 或 目標用電量」二選一,預設 `re_percent` |
| `target_energy_mwh` | `float \| None` | 當 type=`energy` 時的目標綠電量(MWh) |

- 保留現有 `re_target_percent`(type=`re_percent` 時使用)。
- 新增 `app/models/enums.py::GreenTargetType`。

### 台電規則 / 設定 `app/core/config.py`

| 設定 | 預設 | 說明 |
|---|---|---|
| `grey_price_per_kwh` | 3.0 | 灰電(台電)參考電價,算用電端均價/增加成本 |
| `default_feed_in_price_per_kwh` | 4.0 | 風場未填收購價時的回退值 |

> 輸電費率(輸電費)不在 P2 —— PDF p7 的售電毛利 = 售電收入 − 收購成本(不含輸電費),
> 輸電費屬轉供結算,留 P5。

> 皆為全域設定值(MVP);每客戶/時間電價的細緻化留後續階段。

## P2 — 售電評估

新增 `app/services/evaluation.py`。對「某用電戶 + 期間(起訖月,預設全年)」跑**現有月度
媒合引擎**,彙總各月分配後計算雙面報表。媒合引擎本身不改。

### 輸入
- `customer_id`(必要);`start`、`end` 月份(`YYYY-MM`,預設該客戶資料涵蓋的全年)。

### 計算(對齊 PDF p7)
令某期間內對該客戶的每筆分配為 `alloc`(來源風場 `farm`、合約 `contract`、`allocated_mwh`);
度數 = MWh × 1000。

**售電端**(對齊 PDF p7:毛利 = 收入 − 收購成本,不含輸電費)
- 收購成本 = Σ `allocated_kwh × (farm.feed_in_price_per_kwh 或 default)`
- 售電收入 = Σ `allocated_kwh × contract.price_per_kwh`
- 售電毛利 = 售電收入 − 收購成本
- 售電毛利率 = 毛利 / 售電收入(收入為 0 → 0)

**用電端**
- 總用電量 = Σ 該客戶期間 `consumption`(kWh)
- 綠電用電量 = Σ `allocated_kwh`;灰電用電量 = max(0, 總用電 − 綠電)
- 綠電成本 = Σ `allocated_kwh × contract.price_per_kwh`
- 用電平均單價 =(綠電成本 + 灰電度 × grey_price)/ 總度數
- 增加用電成本 = Σ `allocated_kwh × (contract.price_per_kwh − grey_price)`
- RE 比例 = 綠電用電量 / 總用電量(對齊現有 analytics 定義)

### 交付
- API:`GET /api/v1/analytics/evaluation?customer_id=&start=&end=` → `EvaluationResult` schema
  (`app/schemas/evaluation.py`:售電端區塊 + 用電端區塊 + 期間/客戶 meta)。
- 儀表板頁 `dashboard/pages/6_Evaluation.py`:選客戶 + 期間 → 顯示雙欄報表(像 PDF p7)。

## 邊界與決策
- 風場未填收購價 → 回退 `default_feed_in_price_per_kwh`,並於回應標記 `used_default_price`。
- 期間內無媒合/無用電 → 各金額 0、比率 0(不報錯)。
- 一客戶多合約多風場多月 → 逐筆分配加總(不同合約可有不同售價)。

## 測試策略
- 單元(`tests/unit/test_evaluation.py`):給定小型 farms/customers/contracts/gen/consumption,
  斷言收購成本、售電收入、毛利、毛利率、RE%、均價、增加成本;回退預設價;空期間為 0。
- 整合(`tests/integration/test_evaluation_api.py`):seed → `GET evaluation` → 200 + 雙面結構;
  未知客戶 404。
- migration:`alembic upgrade head` 後新欄位存在;既有測試全綠。

## 後續階段(不在本 spec)
P3 經濟最佳化媒合(目標毛利/RE + 約束最小分配%/最少案場數)、P4 時間電價各時段、
P5 轉供結算帳單、電號/契約容量管理。
