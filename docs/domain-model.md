# Domain model

All energy is stored in **MWh**; percentages are 0–100. Defined in `app/models/`.

## Entity–relationship diagram

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

## Key distinctions

The system deliberately keeps these four quantities **separate** — a contract
ratio is *not* the same as the delivered green energy:

| Concept | Field | Meaning |
|---------|-------|---------|
| Contract share | `contracted_percentage` | Agreed share of a farm's output (a cap) |
| Contract volume | `contracted_energy_mwh` | Agreed fixed monthly volume (a cap) |
| Actual generation | `generation_data.generated_energy_mwh` | What the farm really produced |
| Actual consumption | `consumption_data.consumed_energy_mwh` | What the customer really used |
| **Final allocation** | `matching_result.allocated_energy_mwh` | Result of the engine, bounded by all of the above |
| RE achievement | `matching_result.achieved_re_percent` | `allocated ÷ consumption × 100` |

## Enumerations

- **WindFarmStatus**: `planning`, `under_construction`, `operational`, `decommissioned`
- **ContractStatus**: `pending`, `active`, `expired`, `terminated`
- **MatchingRunStatus**: `pending`, `running`, `completed`, `failed`

Only `active` contracts whose `[start_date, end_date]` covers the period take
part in matching (see [`matching-rules.md`](matching-rules.md)).
