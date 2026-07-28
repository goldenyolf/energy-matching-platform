"""B7 — hourly (24/7 CFE) time-coincident matching engine.

A **pure function** over plain dataclasses (no I/O, no global state → same input,
same output), delivering the "重疊才算匹配" rule at hourly resolution:

For each hour ``h`` the engine allocates each farm's generation to its contracted
customers by the same greedy ``min(farm, customer, cap)`` rule the monthly engine
uses — but **strictly within the hour**. Generation left over when no contracted
load is present becomes *surplus* (外溢); load left over when no generation is
present becomes *shortfall* (缺口). Neither is carried to another hour, so this is
真正的時間匹配 — banking would require the storage feature (Roadmap B5).

The headline metric is CFE% (24/7 carbon-free-energy score):

    CFE%(c) = Σₕ matched(c, h) / Σₕ load(c, h) × 100

The engine is generic over the number of buckets ``H`` (24 for hourly; call it
with ``H == 1`` on period totals to get the "帳面" monthly-netting upper bound).
Contract caps are supplied per hour: a percentage cap applies to that hour's farm
generation; a volume cap is pre-distributed across hours by the caller.
"""

from __future__ import annotations

from dataclasses import dataclass, field

_EPS = 1e-9


@dataclass(frozen=True)
class HourlyFarm:
    farm_id: int
    gen: tuple[float, ...]  # length H


@dataclass(frozen=True)
class HourlyCustomer:
    customer_id: int
    load: tuple[float, ...]  # length H


@dataclass(frozen=True)
class HourlyContract:
    contract_id: int
    contract_number: str
    wind_farm_id: int
    customer_id: int
    priority: int = 100
    percentage: float | None = None  # cap = percentage/100 × gen(f, h)
    hourly_cap: tuple[float, ...] | None = None  # per-hour volume cap (Σ = monthly cap)
    order: int = 0  # stable tie-breaker (caller ranks by start_date/number)


@dataclass
class HourlyCustomerResult:
    customer_id: int
    consumption_mwh: float
    matched_mwh: float
    cfe_percent: float
    matched_by_hour: list[float]
    shortfall_by_hour: list[float]


@dataclass
class HourlyFarmResult:
    farm_id: int
    generated_mwh: float
    matched_mwh: float
    surplus_mwh: float
    surplus_by_hour: list[float]


@dataclass
class HourlyOutcome:
    hours: int
    customers: list[HourlyCustomerResult] = field(default_factory=list)
    farms: list[HourlyFarmResult] = field(default_factory=list)
    total_consumption_mwh: float = 0.0
    total_matched_mwh: float = 0.0
    cfe_percent: float = 0.0
    matched_by_hour: list[float] = field(default_factory=list)
    consumption_by_hour: list[float] = field(default_factory=list)
    generation_by_hour: list[float] = field(default_factory=list)
    surplus_by_hour: list[float] = field(default_factory=list)
    shortfall_by_hour: list[float] = field(default_factory=list)


def _infer_hours(farms: list[HourlyFarm], customers: list[HourlyCustomer]) -> int:
    if customers:
        return len(customers[0].load)
    if farms:
        return len(farms[0].gen)
    return 0


def _pct(percent: float | None) -> float:
    return float("inf") if percent is None else percent / 100.0


def match_hourly(
    farms: list[HourlyFarm],
    customers: list[HourlyCustomer],
    contracts: list[HourlyContract],
) -> HourlyOutcome:
    """Allocate generation to load hour-by-hour; only overlap counts."""
    hours = _infer_hours(farms, customers)
    out = HourlyOutcome(hours=hours)
    if hours == 0:
        return out

    gen0 = {f.farm_id: f.gen for f in farms}
    # Per-customer / per-farm accumulators, indexed by hour.
    matched_c = {c.customer_id: [0.0] * hours for c in customers}
    surplus_f = {f.farm_id: [0.0] * hours for f in farms}
    shortfall_c = {c.customer_id: [0.0] * hours for c in customers}

    ordered = sorted(contracts, key=lambda k: (k.priority, k.order, k.contract_id))

    for h in range(hours):
        rem_gen = {f.farm_id: f.gen[h] for f in farms}
        rem_load = {c.customer_id: c.load[h] for c in customers}

        for con in ordered:
            fid, cid = con.wind_farm_id, con.customer_id
            if fid not in rem_gen or cid not in rem_load:
                continue
            cap = min(
                _pct(con.percentage) * gen0[fid][h],
                con.hourly_cap[h] if con.hourly_cap is not None else float("inf"),
            )
            alloc = min(rem_gen[fid], rem_load[cid], cap)
            if alloc <= _EPS:
                continue
            rem_gen[fid] -= alloc
            rem_load[cid] -= alloc
            matched_c[cid][h] += alloc

        for f in farms:
            surplus_f[f.farm_id][h] = rem_gen[f.farm_id]
        for c in customers:
            shortfall_c[c.customer_id][h] = rem_load[c.customer_id]

    for c in customers:
        consumption = sum(c.load)
        matched = sum(matched_c[c.customer_id])
        out.customers.append(
            HourlyCustomerResult(
                customer_id=c.customer_id,
                consumption_mwh=consumption,
                matched_mwh=matched,
                cfe_percent=(
                    (matched / consumption * 100.0) if consumption > _EPS else 0.0
                ),
                matched_by_hour=matched_c[c.customer_id],
                shortfall_by_hour=shortfall_c[c.customer_id],
            )
        )
    for f in farms:
        generated = sum(f.gen)
        surplus = sum(surplus_f[f.farm_id])
        out.farms.append(
            HourlyFarmResult(
                farm_id=f.farm_id,
                generated_mwh=generated,
                matched_mwh=generated - surplus,
                surplus_mwh=surplus,
                surplus_by_hour=surplus_f[f.farm_id],
            )
        )

    out.consumption_by_hour = [sum(c.load[h] for c in customers) for h in range(hours)]
    out.generation_by_hour = [sum(f.gen[h] for f in farms) for h in range(hours)]
    out.matched_by_hour = [
        sum(matched_c[c.customer_id][h] for c in customers) for h in range(hours)
    ]
    out.surplus_by_hour = [
        sum(surplus_f[f.farm_id][h] for f in farms) for h in range(hours)
    ]
    out.shortfall_by_hour = [
        sum(shortfall_c[c.customer_id][h] for c in customers) for h in range(hours)
    ]
    out.total_consumption_mwh = sum(out.consumption_by_hour)
    out.total_matched_mwh = sum(out.matched_by_hour)
    out.cfe_percent = (
        out.total_matched_mwh / out.total_consumption_mwh * 100.0
        if out.total_consumption_mwh > _EPS
        else 0.0
    )
    return out
