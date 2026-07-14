# API 參考

啟動：`uvicorn app.main:app --reload`，互動式文件位於 `http://127.0.0.1:8000/docs`。

## GET /health

健康檢查。

```json
{ "status": "ok", "version": "0.1.0" }
```

## GET /dataset

回傳內建範例資料集（`wind_farms`、`companies`、`contracts`）。

## GET /match

以內建範例資料執行媒合，回傳 `MatchingResult`：

```json
{
  "allocations": [
    {
      "contract_id": "ct-001",
      "company_id": "co-tsmc",
      "wind_farm_id": "wf-greater-changhua",
      "requested_mwh": 3600000.0,
      "allocated_mwh": 3600000.0,
      "curtailed": false
    }
  ],
  "company_results": [
    {
      "company_id": "co-tsmc",
      "name": "台積電",
      "annual_consumption_mwh": 5000000.0,
      "re_target_ratio": 1.0,
      "re_target_mwh": 5000000.0,
      "allocated_mwh": 4850000.0,
      "coverage_ratio": 0.97,
      "target_gap_mwh": 150000.0,
      "target_met": false
    }
  ],
  "wind_farm_results": [ "..." ],
  "summary": {
    "total_generation_mwh": 9900000.0,
    "total_allocated_mwh": 7636000.0,
    "total_surplus_mwh": 2264000.0,
    "utilization_ratio": 0.771313,
    "total_target_gap_mwh": 264000.0,
    "companies_meeting_target": 2,
    "company_count": 5
  }
}
```

## POST /match

以自訂資料集執行媒合。請求 body 為 `Dataset`（結構同 `GET /dataset`）。

- 成功：`200`，回傳 `MatchingResult`。
- 合約引用不存在的案場／企業：`422`，`detail` 說明錯誤。
- 欄位不合法（如 ratio > 1、負電量）：`422`，Pydantic 驗證錯誤。

```bash
curl -X POST http://127.0.0.1:8000/match \
  -H "Content-Type: application/json" \
  -d @data/sample_data.json
```

## GET /companies/{company_id}

回傳指定企業在範例情境下的 `CompanyResult`。

- 找不到：`404`，`{"detail": "找不到企業 ..."}`。

```bash
curl http://127.0.0.1:8000/companies/co-tsmc
```
