# 資料模型

所有電量單位為 **MWh**，比例為 **0..1** 的小數。定義於 `app/models.py`。

## 輸入模型

### WindFarm（風力發電案場）

| 欄位 | 型別 | 說明 |
|------|------|------|
| `id` | str | 唯一識別碼 |
| `name` | str | 案場名稱 |
| `location` | str | 所在縣市／海域 |
| `capacity_mw` | float > 0 | 裝置容量 (MW) |
| `annual_generation_mwh` | float > 0 | 年發電量 (MWh) |
| `capacity_factor` | float（計算屬性） | `年發電量 / (裝置容量 × 8760)` |

### Company（企業用電戶）

| 欄位 | 型別 | 說明 |
|------|------|------|
| `id` | str | 唯一識別碼 |
| `name` | str | 企業名稱 |
| `industry` | str | 產業別 |
| `annual_consumption_mwh` | float > 0 | 年用電量 (MWh) |
| `re_target_ratio` | float 0..1 | RE 目標佔比（RE100 = 1.0） |
| `re_target_mwh` | float（計算屬性） | `年用電量 × RE 目標佔比` |

### Contract（企業綠電合約 / CPPA）

| 欄位 | 型別 | 說明 |
|------|------|------|
| `id` | str | 唯一識別碼 |
| `company_id` | str | 對應企業 |
| `wind_farm_id` | str | 對應案場 |
| `allocation_type` | `ratio` \| `volume` | 分配方式 |
| `value` | float > 0 | ratio：0..1 的比例；volume：年電量 (MWh) |
| `price_per_kwh` | float > 0 | 轉供費率（元/kWh） |
| `start_year` | int | 合約起始年 |

> **驗證規則**：當 `allocation_type = ratio` 時，`value` 必須介於 0 與 1 之間。

### Dataset

一次媒合的完整輸入：`wind_farms[]`、`companies[]`、`contracts[]`。

## 結果模型

### ContractAllocation（單一合約分配）

`contract_id`、`company_id`、`wind_farm_id`、`requested_mwh`（需求）、`allocated_mwh`（實際分配）、`curtailed`（是否因超額認購被削減）。

### CompanyResult（企業 RE 分析）

`allocated_mwh`、`coverage_ratio`（= 分配量 / 用電量）、`re_target_mwh`、`target_gap_mwh`（= max(0, 目標 − 分配)）、`target_met`。

### WindFarmResult（案場利用）

`allocated_mwh`、`surplus_mwh`（剩餘綠電）、`utilization_ratio`、`oversubscribed`。

### PlatformSummary（平台總覽）

`total_generation_mwh`、`total_allocated_mwh`、`total_surplus_mwh`、`utilization_ratio`、`total_target_gap_mwh`、`companies_meeting_target`、`company_count`。

## 關聯圖

```
Company 1 ──< Contract >── 1 WindFarm
   │              │              │
   │ RE 目標分析   │ 分配明細      │ 利用情形
   ▼              ▼              ▼
CompanyResult  ContractAllocation  WindFarmResult
        └──────────┬───────────────┘
                   ▼
            PlatformSummary
```
