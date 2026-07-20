# 領域模型（Domain model）

所有電量以 **MWh** 儲存;百分比為 0–100。定義在 `app/models/`。

## 實體關聯圖（ERD）

```mermaid
erDiagram
    WIND_FARM ||--o{ CONTRACT : "supplies"
    CUSTOMER  ||--o{ CONTRACT : "buys via"
    WIND_FARM ||--o{ GENERATION_DATA : "produces"
    CUSTOMER  ||--o{ CONSUMPTION_DATA : "consumes"
    MATCHING_RUN ||--o{ MATCHING_RESULT : "contains"
    WIND_FARM ||--o{ MATCHING_RESULT : "allocated from"
    CUSTOMER  ||--o{ MATCHING_RESULT : "allocated to"
    CONTRACT  ||--o{ MATCHING_RESULT : "under"

    WIND_FARM {
        int id PK
        string code UK
        string name
        string operator_name
        string location
        float installed_capacity_mw
        date commercial_operation_date
        enum status
    }
    CUSTOMER {
        int id PK
        string code UK
        string company_name
        string industry
        float annual_consumption_mwh
        float re_target_percent
        int target_year
    }
    CONTRACT {
        int id PK
        string contract_number UK
        int wind_farm_id FK
        int customer_id FK
        date start_date
        date end_date
        float contracted_energy_mwh
        float contracted_percentage
        float price_per_kwh
        int priority
        enum status
    }
    GENERATION_DATA {
        int id PK
        int wind_farm_id FK
        date period_start
        date period_end
        float generated_energy_mwh
        string data_source
    }
    CONSUMPTION_DATA {
        int id PK
        int customer_id FK
        date period_start
        date period_end
        float consumed_energy_mwh
        string data_source
    }
    MATCHING_RUN {
        int id PK
        string period
        enum status
        datetime started_at
        datetime completed_at
        json input_summary
        json result_summary
    }
    MATCHING_RESULT {
        int id PK
        int matching_run_id FK
        int wind_farm_id FK
        int customer_id FK
        int contract_id FK
        string period
        float allocated_energy_mwh
        float customer_consumption_mwh
        float achieved_re_percent
        string allocation_reason
    }
```

## 關鍵區別

系統刻意把下面這四個量**分開**——合約比例*不等於*實際交付的綠電:

| 概念 | 欄位 | 意義 |
|---------|-------|---------|
| 合約比例 | `contracted_percentage` | 約定佔某風場產出的比例(上限) |
| 合約電量 | `contracted_energy_mwh` | 約定的固定月度電量(上限) |
| 實際發電 | `generation_data.generated_energy_mwh` | 風場真正發了多少 |
| 實際用電 | `consumption_data.consumed_energy_mwh` | 客戶真正用了多少 |
| **最終分配** | `matching_result.allocated_energy_mwh` | 引擎的結果,受上述所有量所限 |
| RE 達成 | `matching_result.achieved_re_percent` | `分配 ÷ 用電 × 100` |

## 列舉（Enumerations）

- **WindFarmStatus**：`planning`、`under_construction`、`operational`、`decommissioned`
- **ContractStatus**：`pending`、`active`、`expired`、`terminated`
- **MatchingRunStatus**：`pending`、`running`、`completed`、`failed`

只有 `active` 且 `[start_date, end_date]` 涵蓋該期間的合約會參與媒合
(見 [`matching-rules.md`](matching-rules.md))。
