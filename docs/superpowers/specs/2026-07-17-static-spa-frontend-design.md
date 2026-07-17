# 靜態 SPA 前端(v1 旗艦頁)設計

日期:2026-07-17
狀態:已核准方向,待實作
參考:已核准的高保真 mockup(綠電售電評估結果頁);承接 P1–P4a。

## 背景與目標

現有前端為 Streamlit(功能到位、外觀陽春)。本階段依已定版的 mockup,做一個**產品級、
零相依、零 build** 的靜態 SPA,由現有 FastAPI 同源服務,先落地**旗艦頁「最佳化評估」**
(接三個現有 API 端點),並與 Streamlit **並存**(SPA 掛 `/app`,Streamlit :8501 暫留)。

方向決策(已拍板):
- v1 只做 **app shell + 最佳化評估旗艦頁**;其他導覽項先放「目前於 Streamlit」佔位視圖。
- 純 HTML/CSS/vanilla JS,**無框架、無 CDN、無 build**;所有資產自包含。
- SPA 與 Streamlit 並存;FastAPI 掛 `/app`,API 續留 `/api/v1`(**同源、免 CORS**)。
- 表單的「最小分配% / 最少案場數」會真的傳進 `/matching/optimize`;「RE 目標 / 綠電轉供價」
  v1 顯示為唯讀(取自資料設定),表單即時覆寫留 **v1.1(需擴後端)**。

## 架構與檔案結構

```
web/                         # 靜態前端(自包含,無 build)
├── index.html               # app shell + 掛載點(#view)
├── styles.css               # 設計系統(從 mockup 抽出:tokens/明暗/元件)
├── app.js                   # hash router + view 渲染 + 互動(modal/主題)
└── api.js                   # fetch 封裝(同源 /api/v1)
app/main.py                  # 掛 StaticFiles 於 /app
```

- FastAPI(`app/main.py`,在 `include_router` 之後)加:
  ```python
  from pathlib import Path
  from fastapi.staticfiles import StaticFiles

  _WEB_DIR = Path(__file__).resolve().parents[1] / "web"
  app.mount("/app", StaticFiles(directory=str(_WEB_DIR), html=True), name="spa")
  ```
  `html=True` 使 `GET /app/` 回 `index.html`;SPA 路由全在前端(`#/...`),故單一入口即可。
- 同源:SPA 以相對路徑 `"/api/v1/..."` 打 API,無 CORS 問題。

## 設計系統(styles.css)

直接沿用已核准 mockup 的 token 與元件(不再重新設計):
- **色**:中性冷底 + 白卡;深藍品牌軌(明暗都深);品牌/售電端=靛藍 `--seller`、
  用電端=青綠 `--buyer`;狀態 好綠/負紅/premium 琥珀。狀態色與品牌色分離。
- **明暗雙主題**:token 定義於 `:root`,`@media (prefers-color-scheme)` + `:root[data-theme]`
  兩向覆寫;品牌軌兩主題皆深色(刻意)。
- **字**:UI 用系統 zh 字堆;數據/KPI 用等寬 tabular(`font-variant-numeric:tabular-nums`)。
- **元件**:app shell(rail/topbar)、KPI strip、card(含 side-seller/side-buyer 頂邊識別)、
  econ rows、RE gauge、tables(overflow-x auto)、pill/chip/btn、loading modal。
- 響應式:≤1080px 收合側欄與雙欄;寬內容各自 `overflow-x:auto`,body 不橫捲。
- 無障礙:鍵盤 focus 可見;`prefers-reduced-motion` 停動畫。

## app shell(index.html + app.js)

- **側欄**:自繪風能品牌 mark + 「綠電媒合平台 / ENERGY MATCHING」;導覽項:
  發電案場管理、**售電評估工具(active)**、最佳化媒合、時段媒合、轉供結算(disabled/P5)。
- **頂列**:麵包屑 `首頁 › 售電評估工具`、期間 chip、主題切換鈕、說明鈕。
- **router**(hash):`#/evaluate`(旗艦,預設)、其餘導覽項 → `#/soon?page=…` 佔位視圖
  (顯示「此頁目前於 Streamlit 儀表板檢視」+ 該頁說明;不硬接外部 URL)。
- **主題切換**:點鈕在 `:root` 設 `data-theme`(在 media query 之上覆寫,兩向)。

## 旗艦頁「最佳化評估」(#/evaluate)— 接三個現有端點

### 輸入表單
| 欄位 | 來源 / 行為 |
|---|---|
| 用電戶(必選,下拉) | `GET /api/v1/customers` → `{id, code, company_name}` |
| 期間(YYYY-MM,預設 2024-01) | 文字輸入 |
| 最小分配%(number,預設 0) | 傳入 optimize |
| 最少案場數(number,預設 0) | 傳入 optimize |
| RE 目標 / 綠電轉供價(唯讀顯示) | 標註「取自資料設定」;v1 不覆寫 |

提交 → **並行**打三端點(+ 一次性快取 `GET /api/v1/wind-farms` 供 id→名稱):
- `GET /api/v1/matching/optimize?period=&min_sites=&min_site_allocation_percent=`
- `GET /api/v1/analytics/evaluation?customer_id=&start=<period>&end=<period>`
- `GET /api/v1/matching/slots?period=`

令 `focus` = 選定用電戶 `customer_id`。

### 端點 → UI 欄位對映(精確)
`GET /customers` 回 `{id, code, company_name, re_target_percent, ...}`。
`GET /wind-farms` 回 `{id, code, name, ...}`(建 `farmName[id]`)。

**optimize** 回 `{solver_status, objective_gross_margin_ntd, allocations:[{contract_id,
contract_number, wind_farm_id, customer_id, allocated_mwh, contract_limit_mwh, reason}],
customer_targets:[{customer_id, re_target_mwh, allocated_mwh, re_shortfall_mwh,
re_target_met, sites_used, site_shortfall}], farm_summaries:[{wind_farm_id, generated_mwh,
allocated_mwh, unallocated_mwh}], ...}`。

**evaluation** 回 `{seller:{procurement_cost, sales_revenue, gross_profit,
gross_margin_percent}, buyer:{total_consumption_mwh, green_mwh, grey_mwh, re_percent,
avg_price_per_kwh, added_cost}, used_default_feed_in_price}`。

**slots** 回 `{season, slot_breakdown:[{slot, grey_price_per_kwh,
customer_summaries:[{customer_id, consumption_mwh, allocated_mwh, achieved_re_percent}]}]}`。

| UI 區塊 | 對映 |
|---|---|
| pill 求解狀態 | `optimize.solver_status`("Optimal"→ok pill) |
| KPI RE 達成 | `evaluation.buyer.re_percent`(目標 `customer.re_target_percent`) |
| KPI 售電端毛利 | `evaluation.seller.gross_profit`(率 `gross_margin_percent`) |
| KPI 配對案場 | `optimize.customer_targets[focus].sites_used`(容量:所配 farms 之和) |
| KPI 綠電轉供量 / 灰電 | `evaluation.buyer.green_mwh` / `grey_mwh` |
| KPI 售電均價 | `seller.sales_revenue / (buyer.green_mwh×1000)`(綠電轉供均價) |
| KPI 用電均價 | `evaluation.buyer.avg_price_per_kwh` |
| **售電端卡** | `evaluation.seller`(收購成本/售電收入/毛利/毛利率;負值標紅) |
| **用電端卡** gauge | `buyer.re_percent` vs `customer.re_target_percent`;缺口 = 目標−達成 |
| 用電端卡 rows | `buyer.{total_consumption_mwh, green_mwh, grey_mwh, avg_price_per_kwh, added_cost}` |
| 發電端分配概況 | `optimize.allocations` 過濾 `customer_id===focus`,依 farm 加總 |
| 逐案場明細 | 同上逐列:`farmName[wind_farm_id]`、`contract_number`、`allocated_mwh`、`contract_limit_mwh`、分配比例、`reason` |
| 時段別 RE | `slots.slot_breakdown[*]` 取 `customer_summaries` 中 `customer_id===focus`:用電/綠電/RE%;`grey_price_per_kwh`;季別 `slots.season` |

- `used_default_feed_in_price===true` → 售電端卡加註「部分風場未填收購價,已用預設值估算」。

### 狀態
- **載入中**:提交後顯示 loading modal(「正在求解最佳綠電組合…」+ 進度動畫,對標參考版;
  `prefers-reduced-motion` 靜態)。
- **錯誤**:任一端點失敗 → modal 收起,結果區顯示錯誤卡(端點 + 訊息 + 重試鈕)。
- **空**:該期間無資料/該用電戶無分配 → 各數值 0、gauge 0%、表格空列提示,不崩。

## 佔位視圖(#/soon)

其他導覽項顯示卡片:「⏱️ 此頁目前於 Streamlit 儀表板檢視」+ 一句該頁用途;不硬編外部 URL
(Streamlit 位址由使用者自行開啟;避免耦合)。

## 測試策略

- 整合 `tests/integration/test_spa_static.py`:
  - `GET /app/`(client)→ 200 且內容含已知標記(如 `id="view"` 或 `綠電媒合平台`)。
  - `GET /app/styles.css` → 200、`content-type` 為 CSS;`GET /app/app.js` → 200。
  - `GET /app/nonexistent.js` → 404(StaticFiles 行為)。
  - 既有 API 測試不受影響(掛載不改 `/api/v1`)。
- 前端邏輯無 JS 測試框架 → **手動冒煙**(啟後端 → 開 `/app/#/evaluate` → 選用電戶+期間 →
  執行 → 檢查 KPI/雙面卡/逐案場/時段/主題切換/loading modal)。TDD 例外(UI/生成)。
- `index.html`/`app.js`/`styles.css` 以 `python -c "ast/parse"` 無法驗 JS;改以
  瀏覽器 console 無錯 + 版面渲染為準(手動)。

## 邊界與決策
- 同源服務 → API base 為相對 `/api/v1`;開發時後端 :8000 同時服 API 與 `/app`。
- 資產全本地、無 CDN(符合零相依)。視覺化用 CSS(bar/gauge/conic),不引圖表庫。
- 表單「RE 目標 / 綠電轉供價」v1 唯讀;即時覆寫需後端支援(v1.1)。
- 佈署:`web/` 隨 repo;`Dockerfile` 已 `COPY` 專案,FastAPI 服務即含 `/app`(部署文件補一行)。

## 後續(不在本 spec)
- v1.1:後端擴充 per-customer 評估端點(接受表單即時 RE 目標 / 轉供價覆寫),取代 v1 的三端點
  客戶端拼裝;逐時段綠電計價。
- v2:其餘頁(發電案場/客戶/合約/時段媒合)全 SPA 化 → 退掉 Streamlit;圖表(CSS→輕量 canvas)。
