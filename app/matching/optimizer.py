"""MILP economic optimizer for monthly green-energy matching.

A pure function over the same dataclasses the greedy engine uses. Instead of a
priority order, it solves a mixed-integer linear program that maximizes the
retailer's gross margin, treats each customer's RE target as a (softened) hard
constraint, and supports two structural constraints: a minimum number of sites
per customer and a minimum per-site allocation share. See
``docs/matching-rules.md`` and the P3 design spec.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import pulp

from app.matching.engine import (
    _EPS,
    Allocation,
    ContractInput,
    CustomerDemand,
    FarmSupply,
    MatchingOutcome,
    SkippedContract,
    _contract_limit,
    _is_eligible,
    build_customer_summary,
    build_farm_summary,
)

_KWH = 1000.0
_P_RE = 1e6
_P_SITE = 1e3
_EPSILON = 1e-6


@dataclass
class CustomerTarget:
    customer_id: int
    re_target_mwh: float
    allocated_mwh: float
    re_shortfall_mwh: float
    re_target_met: bool
    sites_used: int
    site_shortfall: int


@dataclass
class OptimizationOutcome(MatchingOutcome):
    solver_status: str = "NotSolved"
    objective_gross_margin_ntd: float = 0.0
    customer_targets: list[CustomerTarget] = field(default_factory=list)


@dataclass
class OptimizeOptions:
    min_sites_per_customer: int = 0
    min_site_allocation_percent: float = 0.0
    default_feed_in_price_per_kwh: float = 4.0


def _re_target_mwh(demand: CustomerDemand) -> float:
    cons = demand.consumed_mwh
    ttype = demand.green_target_type or "re_percent"
    if ttype == "energy":
        target = demand.target_energy_mwh or 0.0
    else:
        target = (demand.re_target_percent or 0.0) / 100.0 * cons
    return min(cons, max(0.0, target))


def optimize_period(
    period: str,
    period_start: date,
    period_end: date,
    farms: list[FarmSupply],
    demands: list[CustomerDemand],
    contracts: list[ContractInput],
    options: OptimizeOptions,
) -> OptimizationOutcome:
    """Solve the monthly economic optimization and return a full outcome."""
    # Normalize input order so a non-unique MILP optimum can't differ just
    # because farms/demands were reordered (contracts are already re-sorted
    # into `ordered` below; this extends the same determinism guarantee).
    farms = sorted(farms, key=lambda f: f.farm_id)
    demands = sorted(demands, key=lambda d: d.customer_id)

    generation = {f.farm_id: f.generated_mwh for f in farms}
    consumption = {d.customer_id: d.consumed_mwh for d in demands}
    farm_by_id = {f.farm_id: f for f in farms}

    outcome = OptimizationOutcome(period=period)

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

    # ---- per-contract economics & caps ----
    def feedin(c: ContractInput) -> float:
        farm = farm_by_id.get(c.wind_farm_id)
        val = farm.feed_in_price_per_kwh if farm else None
        return val if val is not None else options.default_feed_in_price_per_kwh

    def price(c: ContractInput) -> float:
        return c.price_per_kwh if c.price_per_kwh is not None else feedin(c)

    def margin(c: ContractInput) -> float:
        return price(c) - feedin(c)

    def cap(c: ContractInput) -> float:
        gen = generation.get(c.wind_farm_id, 0.0)
        lim = _contract_limit(c, gen)
        if lim is None:
            return max(0.0, min(gen, consumption.get(c.customer_id, 0.0)))
        return max(0.0, lim)

    caps = {c.contract_id: cap(c) for c in eligible}

    # ---- decision variables ----
    prob = pulp.LpProblem("green_matching", pulp.LpMaximize)
    alloc = {
        c.contract_id: pulp.LpVariable(
            f"alloc_{c.contract_id}", lowBound=0.0, upBound=caps[c.contract_id]
        )
        for c in eligible
    }
    use = {
        c.contract_id: pulp.LpVariable(f"use_{c.contract_id}", cat="Binary")
        for c in eligible
    }

    contracts_by_customer: dict[int, list[ContractInput]] = {}
    contracts_by_farm: dict[int, list[ContractInput]] = {}
    for c in eligible:
        contracts_by_customer.setdefault(c.customer_id, []).append(c)
        contracts_by_farm.setdefault(c.wind_farm_id, []).append(c)

    # ---- constraints ----
    for fid, cs in contracts_by_farm.items():
        prob += pulp.lpSum(alloc[c.contract_id] for c in cs) <= generation.get(fid, 0.0)

    for kid, cs in contracts_by_customer.items():
        prob += pulp.lpSum(alloc[c.contract_id] for c in cs) <= consumption.get(
            kid, 0.0
        )

    for c in eligible:
        prob += alloc[c.contract_id] <= caps[c.contract_id] * use[c.contract_id]
        floor = (
            options.min_site_allocation_percent
            / 100.0
            * consumption.get(c.customer_id, 0.0)
        )
        # Always tie `use=1` to a strictly positive allocation (at least a
        # token _EPSILON MWh) so `min_sites_per_customer` cannot be satisfied
        # by a "free" binary flag with zero real energy actually delivered.
        prob += alloc[c.contract_id] >= max(floor, _EPSILON) * use[c.contract_id]

    re_short: dict[int, pulp.LpVariable] = {}
    site_short: dict[int, pulp.LpVariable] = {}
    for d in demands:
        kid = d.customer_id
        cs = contracts_by_customer.get(kid, [])
        rs = pulp.LpVariable(f"re_short_{kid}", lowBound=0.0)
        ss = pulp.LpVariable(f"site_short_{kid}", lowBound=0.0)
        re_short[kid] = rs
        site_short[kid] = ss
        prob += pulp.lpSum(alloc[c.contract_id] for c in cs) + rs >= _re_target_mwh(d)
        min_sites = min(options.min_sites_per_customer, len(cs))
        prob += pulp.lpSum(use[c.contract_id] for c in cs) + ss >= min_sites

    # ---- objective (scale-independent penalty hierarchy) ----
    max_abs_margin = max((abs(margin(c)) for c in eligible), default=0.0)
    margin_ub = max(
        1.0, sum(caps[c.contract_id] * _KWH * max_abs_margin for c in eligible)
    )
    margin_term = (
        pulp.lpSum(alloc[c.contract_id] * _KWH * margin(c) for c in eligible)
        / margin_ub
    )
    prob += (
        margin_term
        - _P_RE * pulp.lpSum(re_short.values())
        - _P_SITE * pulp.lpSum(site_short.values())
        - _EPSILON * pulp.lpSum(use.values())
    )

    prob.solve(pulp.PULP_CBC_CMD(msg=0, threads=1))
    outcome.solver_status = pulp.LpStatus[prob.status]

    # ---- extract allocations ----
    alloc_val = {
        c.contract_id: round(max(0.0, alloc[c.contract_id].value() or 0.0), 6)
        for c in eligible
    }
    farm_used: dict[int, float] = {}
    cust_used: dict[int, float] = {}
    for c in eligible:
        v = alloc_val[c.contract_id]
        farm_used[c.wind_farm_id] = farm_used.get(c.wind_farm_id, 0.0) + v
        cust_used[c.customer_id] = cust_used.get(c.customer_id, 0.0) + v

    def opt_reason(c: ContractInput) -> str:
        v = alloc_val[c.contract_id]
        if v <= _EPS:
            return "no allocation: not selected by optimizer"
        binding: list[str] = []
        farm_gen = generation.get(c.wind_farm_id, 0.0)
        if abs(farm_used.get(c.wind_farm_id, 0.0) - farm_gen) <= _EPS:
            binding.append("wind farm supply")
        cust_cons = consumption.get(c.customer_id, 0.0)
        if abs(cust_used.get(c.customer_id, 0.0) - cust_cons) <= _EPS:
            binding.append("customer demand")
        if abs(v - caps[c.contract_id]) <= _EPS:
            binding.append("contract cap")
        where = ", ".join(binding) if binding else "optimizer objective"
        return f"optimized {round(v, 3)} MWh (binding: {where})"

    gross_margin = 0.0
    for c in eligible:
        v = alloc_val[c.contract_id]
        gross_margin += v * _KWH * margin(c)
        lim = _contract_limit(c, generation.get(c.wind_farm_id, 0.0))
        outcome.allocations.append(
            Allocation(
                contract_id=c.contract_id,
                contract_number=c.contract_number,
                wind_farm_id=c.wind_farm_id,
                customer_id=c.customer_id,
                allocated_mwh=v,
                contract_limit_mwh=(None if lim is None else round(lim, 6)),
                reason=opt_reason(c),
            )
        )
    outcome.objective_gross_margin_ntd = round(gross_margin, 6)

    # ---- summaries & customer targets ----
    for d in demands:
        outcome.customer_summaries.append(
            build_customer_summary(
                d.customer_id, d.consumed_mwh, cust_used.get(d.customer_id, 0.0)
            )
        )
    for f in farms:
        outcome.farm_summaries.append(
            build_farm_summary(
                f.farm_id, f.generated_mwh, farm_used.get(f.farm_id, 0.0)
            )
        )

    for d in demands:
        kid = d.customer_id
        cs = contracts_by_customer.get(kid, [])
        target = _re_target_mwh(d)
        allocated = round(cust_used.get(kid, 0.0), 6)
        shortfall = round(max(0.0, target - allocated), 6)
        sites_used = sum(1 for c in cs if alloc_val[c.contract_id] > _EPS)
        min_sites = min(options.min_sites_per_customer, len(cs))
        outcome.customer_targets.append(
            CustomerTarget(
                customer_id=kid,
                re_target_mwh=round(target, 6),
                allocated_mwh=allocated,
                re_shortfall_mwh=shortfall,
                # shortfall is quantized to 6 decimal places (round(..., 6)), so
                # the met-test tolerance must match that rounding grain rather
                # than the much tighter _EPS, or an essentially-met target can
                # be falsely reported as not met.
                re_target_met=shortfall <= 1e-6,
                sites_used=sites_used,
                site_shortfall=max(0, min_sites - sites_used),
            )
        )

    return outcome
