# 台電即時再生能源監控 設計

日期:2026-07-16
狀態:已核准,待實作

## 目標

接台電「各機組發電量即時資訊」開放資料(data.gov.tw #8931,每 10 分鐘更新),
提供**即時監控**:目前風力各機組出力 + 再生能源總覽。這是瞬時 MW 快照,**不入庫、
不進媒合**(與月度 MWh 的 `GenerationData` 本質不同)。

- JSON:`https://service.taipower.com.tw/data/opendata/apply/file/d006001/001.json`
- 結構:`{DateTime, aaData:[{機組類型, 機組名稱, 裝置容量(MW), 淨發電量(MW), ...}]}`
- 機組類型含:燃氣/燃煤/風力/太陽能/水力/儲能… 風力約 31 部機組(含台電自有+離岸)
- 數值有雜訊(如 `3850.0(6.238%)`、`-`、空白)需穩健解析;檔案帶 UTF-8 BOM

## 架構

- `app/ingestion/_http.py`:共用 `http_get(url)`(httpx),taipower.py 與即時 client 共用。
- `app/ingestion/taipower_live.py`:
  - `parse_live(payload) -> LiveRenewables`(純函式)
  - `LiveClient(url, http_get, ttl_seconds=120, clock)`:包 TTL 快取,避免每請求都打台電;
    `http_get` 與 `clock` 皆可注入(測試/替換彈性)。
  - `RENEWABLE_TYPES = {風力, 太陽能, 水力, 地熱, 生質能, 其它再生能源}`(排除儲能/火力)
- `app/schemas/live.py`:`LiveUnit{name, capacity_mw, net_mw}`、
  `RenewableTypeSummary{unit_type, unit_count, net_mw}`、
  `LiveRenewables{snapshot_time, wind[], wind_total_mw, renewable_summary[], renewable_total_mw}`
- `app/api/v1/live.py`:`GET /api/v1/live/renewables`(read-through,`?force=true` 略過快取);
  台電抓取失敗回 503。註冊進 `router.py`。
- `dashboard/pages/5_Live_Renewables.py`:風力各機組表 + 各再生能類型總 MW + 快照時間。

## 相依變更

- httpx 從 `ingestion` extra **移進核心 `dependencies`**(即時端點是一級 API 功能)。
- 移除 `ingestion` extra;更新 taipower.py 的錯誤訊息與 README 對該 extra 的引用。

## 測試

- 單元:`parse_live` fixture(BOM、風力機組、雜訊數字、儲能排除)→ 風力清單、總和、
  再生能總覽、快照時間;`_num` 邊界;`LiveClient` 快取(TTL 內不重抓 / 過期重抓 / force)。
- 整合:TestClient + monkeypatch client → 200 + 結構;抓取失敗 503。

## 明確排除(YAGNI)

- 不入庫、不進媒合、無排程(那是「時序快照入庫」路徑)。
