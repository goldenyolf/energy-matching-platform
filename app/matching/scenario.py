"""Greenfield "what-if" bipartite optimizer for the 多對多匹配 scenario explorer.

Unlike :mod:`app.matching.optimizer` (which flows green energy only along
existing PPA contracts), this optimizer allocates **any** farm to **any**
customer — hypothetical pairings included — under a single assumed transfer
price. It maximizes the retailer's gross margin (buy cheapest green first)
subject to each customer's RE target, then reports which flows correspond to a
real contract so the UI can distinguish reality from what-if.

Pure function, no I/O — same input always yields the same output.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pulp

from app.matching.engine import (
    CustomerDemand,
    CustomerSummary,
    FarmSummary,
    FarmSupply,
    build_customer_summary,
    build_farm_summary,
)
from app.matching.optimizer import CustomerTarget, _re_target_mwh
from app.matching.solver import cbc

# The objective is lexicographic, solved in three phases (see optimize_scenario),
# each a single normalized objective with the previous phase's result locked in:
#   Phase 1 — minimize RE shortfall (≫ site shortfall).
#   Phase 2 — maximize retailer margin (buy cheapest green first).
#   Phase 3 — maximize fairness: spread scarce green so the minimum RE ratio is
#             as high as possible, instead of concentrating it in a few customers.
# Separate phases avoid mixing terms of vastly different scale in one objective,
# where a small secondary term would fall below the solver's working tolerance.
_KWH = 1000.0
_P_RE = 1e3  # phase 1: RE shortfall weight (≫ site)
_P_SITE = 1.0  # phase 1: site shortfall weight
_LOCK_TOL = 1e-9  # tiny FP slack when locking a phase's result into the next
_EPS = 1e-9
_EPSILON = 1e-6


@dataclass
class ScenarioAllocation:
    wind_farm_id: int
    customer_id: int
    allocated_mwh: float
    margin_per_kwh: float
    has_contract: bool


@dataclass
class ScenarioOptions:
    assumed_transfer_price_per_kwh: float = 5.0
    default_feed_in_price_per_kwh: float = 4.0
    min_sites_per_customer: int = 0
    min_site_allocation_percent: float = 0.0


@dataclass
class ScenarioOutcome:
    period: str
    solver_status: str = "NotSolved"
    objective_gross_margin_ntd: float = 0.0
    assumed_transfer_price_per_kwh: float = 0.0
    allocations: list[ScenarioAllocation] = field(default_factory=list)
    customer_targets: list[CustomerTarget] = field(default_factory=list)
    customer_summaries: list[CustomerSummary] = field(default_factory=list)
    farm_summaries: list[FarmSummary] = field(default_factory=list)


def _summaries_only(outcome: ScenarioOutcome, farms, demands) -> ScenarioOutcome:
    """Fill zero-allocation summaries/targets when there is nothing to solve."""
    for d in demands:
        outcome.customer_summaries.append(
            build_customer_summary(d.customer_id, d.consumed_mwh, 0.0)
        )
        target = _re_target_mwh(d)
        outcome.customer_targets.append(
            CustomerTarget(
                customer_id=d.customer_id,
                re_target_mwh=round(target, 6),
                allocated_mwh=0.0,
                re_shortfall_mwh=round(target, 6),
                re_target_met=target <= 1e-6,
                sites_used=0,
                site_shortfall=0,
            )
        )
    for f in farms:
        outcome.farm_summaries.append(
            build_farm_summary(f.farm_id, f.generated_mwh, 0.0)
        )
    outcome.solver_status = "Optimal"
    return outcome


def optimize_scenario(
    period: str,
    farms: list[FarmSupply],
    demands: list[CustomerDemand],
    options: ScenarioOptions,
    contract_pairs: set[tuple[int, int]] | None = None,
) -> ScenarioOutcome:
    """Solve the greenfield bipartite allocation and return a full outcome."""
    # Stable ordering so a degenerate optimum can't differ on input reordering.
    farms = sorted(farms, key=lambda f: f.farm_id)
    demands = sorted(demands, key=lambda d: d.customer_id)
    pairs = contract_pairs or set()

    price = options.assumed_transfer_price_per_kwh
    outcome = ScenarioOutcome(
        period=period, assumed_transfer_price_per_kwh=round(price, 6)
    )
    if not farms or not demands:
        return _summaries_only(outcome, farms, demands)

    gen = {f.farm_id: f.generated_mwh for f in farms}
    # A customer's green ceiling is its RE-TARGET energy, not its full
    # consumption: we never allocate a customer more green than it asked for, so
    # the achieved RE% never exceeds the target the user set (surplus green stays
    # unsold as farm surplus). This mirrors reality — green demand is bounded by
    # the customer's RE commitment, not by pushing all of a farm's generation.
    green_need = {d.customer_id: _re_target_mwh(d) for d in demands}

    def feedin(f: FarmSupply) -> float:
        return (
            f.feed_in_price_per_kwh
            if f.feed_in_price_per_kwh is not None
            else options.default_feed_in_price_per_kwh
        )

    margin = {f.farm_id: price - feedin(f) for f in farms}

    def cap(fid: int, kid: int) -> float:
        return max(0.0, min(gen[fid], green_need[kid]))

    prob = pulp.LpProblem("scenario_matching", pulp.LpMaximize)
    alloc: dict[tuple[int, int], pulp.LpVariable] = {}
    use: dict[tuple[int, int], pulp.LpVariable] = {}
    for f in farms:
        for d in demands:
            key = (f.farm_id, d.customer_id)
            alloc[key] = pulp.LpVariable(
                f"a_{f.farm_id}_{d.customer_id}", lowBound=0.0, upBound=cap(*key)
            )
            use[key] = pulp.LpVariable(f"u_{f.farm_id}_{d.customer_id}", cat="Binary")

    # farm supply is a finite pool
    for f in farms:
        prob += (
            pulp.lpSum(alloc[(f.farm_id, d.customer_id)] for d in demands)
            <= gen[f.farm_id]
        )
    # a customer never receives more green than its RE target requires
    for d in demands:
        prob += (
            pulp.lpSum(alloc[(f.farm_id, d.customer_id)] for f in farms)
            <= green_need[d.customer_id]
        )

    # link use → allocation, and enforce the minimum per-site allocation floor
    for f in farms:
        for d in demands:
            key = (f.farm_id, d.customer_id)
            prob += alloc[key] <= cap(*key) * use[key]
            floor = (
                options.min_site_allocation_percent / 100.0 * green_need[d.customer_id]
            )
            prob += alloc[key] >= max(floor, _EPSILON) * use[key]

    # RE target (soft) + minimum sites per customer (soft)
    re_short: dict[int, pulp.LpVariable] = {}
    site_short: dict[int, pulp.LpVariable] = {}
    for d in demands:
        kid = d.customer_id
        rs = pulp.LpVariable(f"re_short_{kid}", lowBound=0.0)
        ss = pulp.LpVariable(f"site_short_{kid}", lowBound=0.0)
        re_short[kid] = rs
        site_short[kid] = ss
        prob += pulp.lpSum(
            alloc[(f.farm_id, kid)] for f in farms
        ) + rs >= _re_target_mwh(d)
        min_sites = min(options.min_sites_per_customer, len(farms))
        prob += pulp.lpSum(use[(f.farm_id, kid)] for f in farms) + ss >= min_sites

    # Fairness: raise the minimum RE-satisfaction ratio across customers so that
    # scarce green spreads proportionally instead of concentrating in a few
    # customers. This is a margin-neutral tie-break within the min-shortfall
    # optimum set (single transfer price → margin is indifferent to which
    # customer is served), weighted below the RE/site penalties.
    z_floor = pulp.LpVariable("re_ratio_floor", lowBound=0.0, upBound=1.0)
    for d in demands:
        target = _re_target_mwh(d)
        if target > _EPS:
            prob += (
                pulp.lpSum(alloc[(f.farm_id, d.customer_id)] for f in farms)
                >= z_floor * target
            )

    # objective terms, each normalized to ~[0, 1] before weighting
    max_abs_margin = max((abs(m) for m in margin.values()), default=0.0)
    total_cap = sum(cap(f.farm_id, d.customer_id) for f in farms for d in demands)
    margin_ub = max(1.0, total_cap * _KWH * max_abs_margin)
    margin_term = (
        pulp.lpSum(
            alloc[(f.farm_id, d.customer_id)] * _KWH * margin[f.farm_id]
            for f in farms
            for d in demands
        )
        / margin_ub
    )
    re_ub = max(1.0, sum(_re_target_mwh(d) for d in demands))
    site_ub = max(
        1.0, float(min(options.min_sites_per_customer, len(farms)) * len(demands))
    )
    re_sum = pulp.lpSum(re_short.values())
    site_sum = pulp.lpSum(site_short.values())
    # Exact solve (no MIP gap): later phases optimize a term that is small in
    # absolute value, so an early gap-based stop would drop it.
    solver = cbc(exact=True)

    # Phase 1 — minimize RE shortfall (≫ site shortfall).
    prob += -_P_RE * (re_sum / re_ub) - _P_SITE * (site_sum / site_ub)
    prob.solve(solver)
    re_opt = sum(v.value() or 0.0 for v in re_short.values())
    site_opt = sum(v.value() or 0.0 for v in site_short.values())
    prob += re_sum <= re_opt + _LOCK_TOL
    prob += site_sum <= site_opt + _LOCK_TOL

    # Phase 2 — maximize retailer margin (buy cheapest green first).
    prob.setObjective(margin_term)
    prob.solve(solver)
    margin_opt = pulp.value(margin_term) or 0.0
    prob += margin_term >= margin_opt - _LOCK_TOL

    # Phase 3 — maximize fairness (spread scarce green); tiny site tie-break.
    prob.setObjective(z_floor - _EPSILON * pulp.lpSum(use.values()))
    prob.solve(solver)
    outcome.solver_status = pulp.LpStatus[prob.status]

    val: dict[tuple[int, int], float] = {}
    farm_used: dict[int, float] = {}
    cust_used: dict[int, float] = {}
    for f in farms:
        for d in demands:
            key = (f.farm_id, d.customer_id)
            v = round(max(0.0, alloc[key].value() or 0.0), 6)
            val[key] = v
            farm_used[f.farm_id] = farm_used.get(f.farm_id, 0.0) + v
            cust_used[d.customer_id] = cust_used.get(d.customer_id, 0.0) + v

    gross = 0.0
    for f in farms:
        for d in demands:
            key = (f.farm_id, d.customer_id)
            v = val[key]
            gross += v * _KWH * margin[f.farm_id]
            if v > _EPS:
                outcome.allocations.append(
                    ScenarioAllocation(
                        wind_farm_id=f.farm_id,
                        customer_id=d.customer_id,
                        allocated_mwh=v,
                        margin_per_kwh=round(margin[f.farm_id], 6),
                        has_contract=key in pairs,
                    )
                )
    outcome.objective_gross_margin_ntd = round(gross, 6)

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
        target = _re_target_mwh(d)
        allocated = round(cust_used.get(kid, 0.0), 6)
        shortfall = round(max(0.0, target - allocated), 6)
        sites_used = sum(1 for f in farms if val[(f.farm_id, kid)] > _EPS)
        min_sites = min(options.min_sites_per_customer, len(farms))
        outcome.customer_targets.append(
            CustomerTarget(
                customer_id=kid,
                re_target_mwh=round(target, 6),
                allocated_mwh=allocated,
                re_shortfall_mwh=shortfall,
                re_target_met=shortfall <= 1e-6,
                sites_used=sites_used,
                site_shortfall=max(0, min_sites - sites_used),
            )
        )

    return outcome
