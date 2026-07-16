# Matching rules

The matching engine (`app/matching/engine.py`) allocates each wind farm's monthly
generation to customers through their contracts, deterministically.

## Inputs

For a single period (one calendar month, `YYYY-MM`):

- **Farm supply** — each farm's total `generated_energy_mwh` that month.
- **Customer demand** — each customer's total `consumed_energy_mwh` that month.
- **Contracts** — every contract, with its priority, validity window, status and
  cap (`contracted_energy_mwh` and/or `contracted_percentage`).

## Process flow

```mermaid
flowchart TD
    A[Start: period YYYY-MM] --> B[Sum generation per farm<br/>Sum consumption per customer]
    B --> C[Sort contracts by<br/>priority ASC, start_date ASC, contract_number ASC]
    C --> D{Next contract}
    D -->|eligible?| E{active AND<br/>valid in period?}
    E -->|no| F[Skip: record reason]
    F --> D
    E -->|yes| G[limit = min of contract caps<br/>volume and/or % of farm gen]
    G --> H["allocation = min(<br/>farm remaining,<br/>customer remaining demand,<br/>contract limit)"]
    H --> I[Record allocation + binding reason]
    I --> J[Decrement farm remaining<br/>Increment customer allocated]
    J --> D
    D -->|no more| K[Compute per-customer RE %<br/>per-farm unallocated<br/>gaps to target]
    K --> L[Return MatchingOutcome]
```

## Allocation rules

1. **Period = one month.** Generation and consumption are aggregated to the month.
2. **No double allocation.** Each farm's generated energy is a finite pool;
   `Σ allocations from a farm ≤ its generation`.
3. **No over-consumption.** `Σ allocations to a customer ≤ its consumption`.
4. **Contract cap.** A contract never allocates more than the tighter of its
   fixed volume and its percentage-of-generation share.
5. **Priority.** Contracts are served by ascending `priority` (lower number =
   higher priority). Ties break by earlier `start_date`, then `contract_number` —
   a total, stable ordering.
6. **Eligibility.** Only `active` contracts with `start_date ≤ period_end` and
   `end_date ≥ period_start` participate. Others are skipped with a recorded
   reason (not started / already ended / not active).
7. **Auditability.** Every allocation records the binding constraint
   ("limited by wind farm supply / customer demand / contract cap").
8. **Determinism.** No randomness; identical inputs give identical outputs.

## Formulas

```
contract_limit      = min( contracted_energy_mwh?,
                           contracted_percentage/100 × farm_generation? )
allocation          = max(0, min(farm_remaining, customer_remaining, contract_limit))
achieved_re_percent = allocated_to_customer / customer_consumption × 100
target_energy_mwh   = customer_consumption × re_target_percent / 100
gap_to_target_mwh   = max(0, target_energy_mwh − allocated_to_customer)
utilization_percent = allocated_from_farm / farm_generation × 100
```

## Boundary scenarios (all covered by the demo data)

| Scenario | How it shows up |
|----------|-----------------|
| Under-supply | Large customer (TSMC) — RE% < target, positive gap |
| Over-supply | Small farm (Zhongtun) generates more than its single small buyer uses → unallocated surplus |
| Consumption below contract cap | Customer capped by demand, not by the contract |
| Different RE targets | 100 % / 60 % / 80 % / 50 % across customers |
| Different priorities | Higher-priority contract on a shared farm served first |
| Contract inactive | Expired (`PPA-2020-007`) and pending (`PPA-2025-008`) are skipped |

## Limitations & future optimisation

- Monthly granularity only — no 8760-hour time-matching yet (Phase 2).
- Greedy priority allocation, not a global optimum. A future phase can replace
  the greedy pass with a linear program that minimises total gap or cost while
  respecting the same constraints (Phase 3).
- No inter-farm portfolio balancing or curtailment forecasting yet.

## 經濟最佳化媒合(optimizer)

`app/matching/optimizer.py::optimize_period` 是第二種媒合策略:不依優先序貪婪分配,
而是以 MILP(PuLP + 內建 CBC)對整個期間**全域求解**。

**目標**:最大化售電端總毛利。先將毛利正規化到 `[−1, 1]`:
`margin_term = Σ alloc×1000×margin / MARGIN_UB`,再扣除**尺度無關的懲罰階層**
`P_RE(1e6) ≫ P_SITE(1e3) ≫ margin_term ≫ ε(1e-6)`,依序對應 RE 缺口、最少案場缺口、
毛利本身、案場數破平局。

**決策變數**:每筆合格合約各有 `alloc[c] ≥ 0`(MWh)與 `use[c] ∈ {0,1}`(是否啟用)。

**約束**:場供給(`Σalloc ≤ 發電量`)、客戶需求(`Σalloc ≤ 用電量`)、合約上限與啟用
連結(`alloc ≤ cap × use`)、最小分配% 為**硬**下限(啟用中的案場須至少提供該客戶
用電量的 `min_site_allocation_percent`%,且此連結使啟用永遠對應嚴格大於 0 的分配,
不能靠空 flag 湊數)、最少案場數與 RE 目標皆為**軟**約束(以 slack 變數表示,恆可行,
可行時等效硬約束、不可行時自動最小化缺口)。

**可重現性**:單執行緒求解(`PULP_CBC_CMD(threads=1, msg=0)`)、合約以穩定序建模、
目標以 ε 項破平局,同一輸入(即使重新排序)求解結果逐筆相同。
