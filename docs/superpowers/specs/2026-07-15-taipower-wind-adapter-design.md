# 台電風力開放資料 Adapter 設計

日期:2026-07-15
狀態:已核准,待實作

## 目標

實作 `app/ingestion/sources.py` 中預留的 Phase-2 真實資料來源,把台灣電力公司在
政府資料開放平臺(data.gov.tw)發布的「風機發電量及發電時數統計表」接進現有的
ingestion 流程,產生可用於媒合的風場與逐月發電資料。

- 資料集:<https://data.gov.tw/dataset/29961>
- CSV 下載:`https://service.taipower.com.tw/data/opendata/apply/file/d693004/001.csv`
- 授權:政府資料開放授權條款第 1 版(免費、可商用)
- 更新頻率:每月;格式 CSV(UTF-8 附 BOM)

## 來源資料形狀(實測)

每列 = 單一風機 × 單一月份。欄位:

| 欄位 | 說明 |
|---|---|
| 年度/Year | 例 2016 |
| 月份/Month | `01`..`12` |
| 縣市/County | 例 `新北市/New Taipei City` |
| 縣市別代碼/CountyCode | 例 65000 |
| 發電站名稱/Station Name | 例 `石門風電站/Shimen Wind Power Station` |
| 風機編號/Wind Turbine Number | 例 `#1` |
| 裝置容量(kW) | 例 660 |
| 風機發電量(度)/kWh | 例 252168;缺值以 `-` 表示 |
| 風機發電時數(小時) | 缺值 `-` |
| 風機未發電時數(小時) | 缺值 `-` |

範圍:2016 至今,整份約 2.4 MB。這些是**台電自有**(多為陸域)風場,與 demo
sample 的離岸風場(Formosa 2、Changfang 等 IPP)是**不同群體**。

## 架構

新增單一模組 `app/ingestion/taipower.py`,內含 `TaipowerWindSource`,實作既有的
`DataSource` protocol,因此可直接接進 `csv_importer` 與 `seed.py`,系統其餘部分不動。

```
TaipowerWindSource(months=12, csv_path=None, fetch=False, url=DEFAULT_URL)
```

`months` = 匯入資料檔中「最新 N 個月」的滾動視窗(以檔案內最新月份為基準往回推,可跨
年度邊界)。預設 12。

- `_load_rows()`:`fetch=True` → 以 httpx(延遲載入)下載 CSV 到記憶體;否則讀本地檔
  (預設 `data/taipower/wind_turbines.csv`)。兩者都經現有 `parse_csv()`(已處理 BOM)。

### 五個 protocol 方法

- 視窗:先掃出資料中所有 (年, 月),取最新 N 個月為 `_window`,`wind_farms()` 與
  `generation()` 都只看落在視窗內的列。
- `wind_farms()`:依站名分組,每站一個風場。
  - `code = TPC-<SLUG>`,SLUG 取英文站名去掉 `Wind Power Station` 後大寫(例 `TPC-SHIMEN`)
  - `name` = 完整站名;`location` = 縣市;`operator_name = "台灣電力公司"`
  - `installed_capacity_mw` = Σ 視窗內該站各風機 kW ÷ 1000
  - `status = operational`
- `generation()`:依(站, 年, 月)分組,加總各風機「風機發電量(度)」,跳過 `-`。輸出
  `wind_farm_code=TPC-<SLUG>`、`period_start`=當月 1 日、`period_end`=當月最後一日、
  `generated_energy_mwh` = Σ kWh ÷ 1000、`data_source="taipower"`。
- `customers()` / `contracts()` / `consumption()`:回傳 `[]`(台電無需求端資料)。

### 接線

- `scripts/seed.py`:新增 `--source {sample,taipower}`、`--months`、`--fetch`、`--csv-path`。
  預設 `sample` 行為不變。`taipower` 換成 `TaipowerWindSource`;`TPC-` 與 `WF-` 並存。
- 預設值(URL、CSV 路徑、月數)以 `taipower.py` 的模組常數提供;覆寫透過上述 CLI 旗標。
  (原設計曾規劃在 `config.py` 新增 Settings 欄位,實作時改以 `--csv-path` 等 CLI 旗標覆寫,
  避免引入未被讀取的設定。原本的「單一年度」過濾亦已改為「最近 N 個月」滾動視窗。)
- `pyproject.toml`:新增選用 extra `ingestion = ["httpx>=0.27"]`。預設本地檔路徑不需新
  runtime 相依;`--fetch` 才延遲載入 httpx。
- 移除 `sources.py` 中已被取代的 `PublicDataAdapter` 佔位類別。

## 錯誤處理

- 本地檔不存在 → 明確錯誤,指示改用 `--fetch` 或提供下載 URL。
- `--fetch` 但未安裝 httpx → 提示安裝 `.[ingestion]` extra。
- 數值欄位無法解析 → 跳過該筆(不致命),與 importer 既有逐列容錯一致。

## 測試

- `tests/unit/test_taipower_source.py`:小型記憶體 CSV fixture(多站/多風機、一個 `-`
  列、兩個年度),驗證站別去重 + 容量加總、年度過濾、風機加總、kWh→MWh 換算、`-` 跳過、
  需求端為空。fetch 路徑用 monkeypatch 的 httpx,**不碰真實網路**。
- 整合測試:把 fixture 透過 `csv_importer` 端到端 seed 一次,確認 import 成功。

## 明確排除(YAGNI)

- 不做即時(每 10 分鐘)各機組 JSON 來源。
- 不合併台電風場與離岸 demo 風場為同一實體。
- 不自動排程更新;更新由使用者手動 `--fetch` 觸發。
