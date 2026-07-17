"""Joint per-time-slot MILP optimizer (P4b).

Solves all three Taipower time slots (peak / half-peak / off-peak) together in a
single MILP, because a customer's RE target is a cross-slot aggregate. Objective:
minimize total generation allocation (patent eq.7) subject to per-slot transfer
caps (eq.5), a softened-hard RE target, and the min-site-% / min-sites structural
constraints. Global per-slot optimization redistributes same-slot surplus across
customers — Taipower secondary matching. Pure and deterministic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import pulp

from app.matching.engine import (
    _EPS,
    ContractInput,
    SkippedContract,
    _is_eligible,
)
from app.matching.slot_engine import SlotCustomerDemand, SlotFarmSupply
from app.matching.tou import SLOT_ORDER, season_of
from app.models.enums import Season, TimeSlot

_KWH = 1000.0
_P_RE = 1e6
_P_SITE = 1e3
_EPSILON = 1e-6


@dataclass
class SlotOptimizeOptions:
    min_sites_per_customer: int = 0
    min_site_allocation_percent: float = 0.0
    re_target_percent_override: dict[int, float] | None = None
    default_feed_in_price_per_kwh: float = 4.0


@dataclass
class SlotOptAllocation:
    contract_id: int
    contract_number: str
    wind_farm_id: int
    customer_id: int
    slot: TimeSlot
    allocated_mwh: float
    reason: str


@dataclass
class CustomerSlotRow:
    customer_id: int
    slot: TimeSlot
    consumption_mwh: float
    allocated_mwh: float
    re_percent: float


@dataclass
class CustomerTotal:
    customer_id: int
    consumption_mwh: float
    allocated_mwh: float
    re_percent: float
    re_shortfall_mwh: float
    sites_used: int
    site_shortfall: int


@dataclass
class FarmTotal:
    farm_id: int
    generated_mwh: float
    allocated_mwh: float


@dataclass
class SlotOptimizationOutcome:
    period: str
    season: Season
    solver_status: str = "NotSolved"
    allocations: list[SlotOptAllocation] = field(default_factory=list)
    skipped: list[SkippedContract] = field(default_factory=list)
    customer_slot: list[CustomerSlotRow] = field(default_factory=list)
    customer_totals: list[CustomerTotal] = field(default_factory=list)
    farm_totals: list[FarmTotal] = field(default_factory=list)


def optimize_slots(
    period: str,
    period_start: date,
    period_end: date,
    farms: list[SlotFarmSupply],
    demands: list[SlotCustomerDemand],
    contracts: list[ContractInput],
    options: SlotOptimizeOptions,
) -> SlotOptimizationOutcome:
    season = season_of(period_start.month)
    outcome = SlotOptimizationOutcome(period=period, season=season)

    gen: dict[tuple[int, TimeSlot], float] = {}
    for f in farms:
        gen[(f.farm_id, f.slot)] = gen.get((f.farm_id, f.slot), 0.0) + f.generated_mwh
    con: dict[tuple[int, TimeSlot], float] = {}
    target_of: dict[int, tuple[str | None, float | None, float | None]] = {}
    for d in demands:
        con[(d.customer_id, d.slot)] = (
            con.get((d.customer_id, d.slot), 0.0) + d.consumed_mwh
        )
        target_of.setdefault(
            d.customer_id,
            (d.green_target_type, d.re_target_percent, d.target_energy_mwh),
        )

    farm_ids = sorted({f.farm_id for f in farms})
    cust_ids = sorted({d.customer_id for d in demands})
    con_total = {k: sum(con.get((k, s), 0.0) for s in SLOT_ORDER) for k in cust_ids}
    override = options.re_target_percent_override or {}

    def re_target(k: int) -> float:
        cons = con_total.get(k, 0.0)
        if k in override:
            t = override[k] / 100.0 * cons
        else:
            typ, pct, energy = target_of.get(k, (None, None, None))
            if (typ or "re_percent") == "energy":
                t = energy or 0.0
            else:
                t = (pct or 0.0) / 100.0 * cons
        return min(cons, max(0.0, t))

    ordered = sorted(
        contracts, key=lambda c: (c.priority, c.start_date, c.contract_number)
    )
    eligible: list[ContractInput] = []
    for c in ordered:
        skip = _is_eligible(c, period_start, period_end)
        if skip is not None:
            outcome.skipped.append(
                SkippedContract(c.contract_id, c.contract_number, skip)
            )
        else:
            eligible.append(c)

    by_cust: dict[int, list[ContractInput]] = {}
    by_farm: dict[int, list[ContractInput]] = {}
    for c in eligible:
        by_cust.setdefault(c.customer_id, []).append(c)
        by_farm.setdefault(c.wind_farm_id, []).append(c)

    def slot_cap(c: ContractInput, s: TimeSlot) -> float:
        g = gen.get((c.wind_farm_id, s), 0.0)
        if c.contracted_percentage is not None:
            return max(0.0, c.contracted_percentage / 100.0 * g)
        return max(0.0, min(g, con.get((c.customer_id, s), 0.0)))

    prob = pulp.LpProblem("slot_opt", pulp.LpMinimize)
    alloc: dict[tuple[int, TimeSlot], pulp.LpVariable] = {}
    for c in eligible:
        for s in SLOT_ORDER:
            alloc[(c.contract_id, s)] = pulp.LpVariable(
                f"a_{c.contract_id}_{s.value}", lowBound=0.0, upBound=slot_cap(c, s)
            )
    use = {
        c.contract_id: pulp.LpVariable(f"u_{c.contract_id}", cat="Binary")
        for c in eligible
    }
    re_short = {k: pulp.LpVariable(f"re_{k}", lowBound=0.0) for k in cust_ids}
    site_short = {k: pulp.LpVariable(f"ss_{k}", lowBound=0.0) for k in cust_ids}

    # (1) per-slot farm supply (eq.5)
    for f_id, cs in by_farm.items():
        for s in SLOT_ORDER:
            prob += pulp.lpSum(alloc[(c.contract_id, s)] for c in cs) <= gen.get(
                (f_id, s), 0.0
            )
    # (2) per-slot customer demand (eq.5)
    for k, cs in by_cust.items():
        for s in SLOT_ORDER:
            prob += pulp.lpSum(alloc[(c.contract_id, s)] for c in cs) <= con.get(
                (k, s), 0.0
            )
    # (4) monthly energy cap; (5) use link + min-% floor
    for c in eligible:
        total_c = pulp.lpSum(alloc[(c.contract_id, s)] for s in SLOT_ORDER)
        use_cap = sum(slot_cap(c, s) for s in SLOT_ORDER)
        if c.contracted_energy_mwh is not None:
            prob += total_c <= c.contracted_energy_mwh
            use_cap = min(use_cap, c.contracted_energy_mwh)
        prob += total_c <= use_cap * use[c.contract_id]
        floor = (
            options.min_site_allocation_percent
            / 100.0
            * con_total.get(c.customer_id, 0.0)
        )
        prob += total_c >= max(floor, _EPSILON) * use[c.contract_id]
    # (6) min sites (soft); (7) RE cross-slot (soft)
    for k in cust_ids:
        cs = by_cust.get(k, [])
        min_sites = min(options.min_sites_per_customer, len(cs))
        prob += pulp.lpSum(use[c.contract_id] for c in cs) + site_short[k] >= min_sites
        prob += pulp.lpSum(
            alloc[(c.contract_id, s)] for c in cs for s in SLOT_ORDER
        ) + re_short[k] >= re_target(k)

    # objective (eq.7): minimize total allocation, then penalties
    prob += (
        pulp.lpSum(
            alloc[(c.contract_id, s)] * _KWH for c in eligible for s in SLOT_ORDER
        )
        + _P_RE * pulp.lpSum(re_short[k] * _KWH for k in cust_ids)
        + _P_SITE * pulp.lpSum(site_short[k] for k in cust_ids)
        + _EPSILON * pulp.lpSum(use[c.contract_id] for c in eligible)
    )

    prob.solve(pulp.PULP_CBC_CMD(msg=0, threads=1))
    outcome.solver_status = pulp.LpStatus[prob.status]

    av: dict[tuple[int, TimeSlot], float] = {
        (c.contract_id, s): round(max(0.0, alloc[(c.contract_id, s)].value() or 0.0), 6)
        for c in eligible
        for s in SLOT_ORDER
    }

    for c in eligible:
        for s in SLOT_ORDER:
            v = av[(c.contract_id, s)]
            reason = (
                f"optimized {round(v, 3)} MWh ({s.value})"
                if v > _EPS
                else "no allocation (per-slot optimum)"
            )
            outcome.allocations.append(
                SlotOptAllocation(
                    c.contract_id,
                    c.contract_number,
                    c.wind_farm_id,
                    c.customer_id,
                    s,
                    v,
                    reason,
                )
            )

    for k in cust_ids:
        cs = by_cust.get(k, [])
        for s in SLOT_ORDER:
            cons = con.get((k, s), 0.0)
            a = sum(av[(c.contract_id, s)] for c in cs)
            outcome.customer_slot.append(
                CustomerSlotRow(
                    k,
                    s,
                    round(cons, 6),
                    round(a, 6),
                    round(a / cons * 100.0, 4) if cons else 0.0,
                )
            )
        cons_t = con_total.get(k, 0.0)
        a_t = sum(av[(c.contract_id, s)] for c in cs for s in SLOT_ORDER)
        tgt = re_target(k)
        sites = sum(
            1 for c in cs if sum(av[(c.contract_id, s)] for s in SLOT_ORDER) > _EPS
        )
        min_sites = min(options.min_sites_per_customer, len(cs))
        outcome.customer_totals.append(
            CustomerTotal(
                k,
                round(cons_t, 6),
                round(a_t, 6),
                round(a_t / cons_t * 100.0, 4) if cons_t else 0.0,
                round(max(0.0, tgt - a_t), 6),
                sites,
                max(0, min_sites - sites),
            )
        )

    for f_id in farm_ids:
        generated = sum(gen.get((f_id, s), 0.0) for s in SLOT_ORDER)
        a = sum(
            av[(c.contract_id, s)] for c in by_farm.get(f_id, []) for s in SLOT_ORDER
        )
        outcome.farm_totals.append(FarmTotal(f_id, round(generated, 6), round(a, 6)))

    return outcome
