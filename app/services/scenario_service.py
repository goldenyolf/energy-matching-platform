"""Scenario-explorer service: filter the universe, override RE targets, solve.

Loads a period's farms/customers/generation/consumption, restricts them to a
user-selected subset, applies per-customer RE-target overrides, then runs the
greenfield :func:`app.matching.scenario.optimize_scenario`. Compute-only, no
persistence — mirrors :mod:`app.services.optimize_service`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.matching.engine import (
    ContractInput,
    CustomerDemand,
    FarmSupply,
    _is_eligible,
)
from app.matching.scenario import ScenarioOptions, optimize_scenario
from app.models import Contract, Customer, WindFarm
from app.schemas.optimization import (
    OptCustomerSummary,
    OptCustomerTarget,
    OptFarmSummary,
)
from app.schemas.scenario import ScenarioAllocationOut, ScenarioResult
from app.services.matching_service import (
    _sum_consumption,
    _sum_generation,
    period_bounds,
)


@dataclass
class ScenarioRequest:
    farm_ids: set[int] | None = None  # None = all farms
    customer_ids: set[int] | None = None  # None = all customers
    re_target_overrides: dict[int, float] = field(default_factory=dict)
    assumed_transfer_price_per_kwh: float = 5.0
    min_sites_per_customer: int = 0
    min_site_allocation_percent: float = 0.0
    default_feed_in_price_per_kwh: float = 4.0


def compute_scenario(db: Session, period: str, req: ScenarioRequest) -> ScenarioResult:
    start, end = period_bounds(period)
    gen = _sum_generation(db, start, end)
    con = _sum_consumption(db, start, end)

    farms = [
        FarmSupply(
            farm_id=f.id,
            generated_mwh=gen.get(f.id, 0.0),
            feed_in_price_per_kwh=f.feed_in_price_per_kwh,
        )
        for f in db.execute(select(WindFarm).order_by(WindFarm.id)).scalars()
        if req.farm_ids is None or f.id in req.farm_ids
    ]
    demands = [
        CustomerDemand(
            customer_id=c.id,
            consumed_mwh=con.get(c.id, 0.0),
            green_target_type=(
                "re_percent"
                if c.id in req.re_target_overrides
                else c.green_target_type.value
            ),
            re_target_percent=req.re_target_overrides.get(c.id, c.re_target_percent),
            target_energy_mwh=c.target_energy_mwh,
        )
        for c in db.execute(select(Customer).order_by(Customer.id)).scalars()
        if req.customer_ids is None or c.id in req.customer_ids
    ]

    farm_id_set = {f.farm_id for f in farms}
    cust_id_set = {d.customer_id for d in demands}

    # Which selected (farm, customer) pairs have a PPA that is eligible this
    # period — so the UI can tell reality (solid) from what-if (dashed).
    contract_pairs: set[tuple[int, int]] = set()
    for c in db.execute(select(Contract)).scalars():
        if c.wind_farm_id not in farm_id_set or c.customer_id not in cust_id_set:
            continue
        contract = ContractInput(
            contract_id=c.id,
            contract_number=c.contract_number,
            wind_farm_id=c.wind_farm_id,
            customer_id=c.customer_id,
            start_date=c.start_date,
            end_date=c.end_date,
            status=c.status.value,
            priority=c.priority,
        )
        if _is_eligible(contract, start, end) is None:
            contract_pairs.add((c.wind_farm_id, c.customer_id))

    outcome = optimize_scenario(
        period,
        farms,
        demands,
        ScenarioOptions(
            assumed_transfer_price_per_kwh=req.assumed_transfer_price_per_kwh,
            default_feed_in_price_per_kwh=req.default_feed_in_price_per_kwh,
            min_sites_per_customer=req.min_sites_per_customer,
            min_site_allocation_percent=req.min_site_allocation_percent,
        ),
        contract_pairs=contract_pairs,
    )

    return ScenarioResult(
        period=period,
        solver_status=outcome.solver_status,
        objective_gross_margin_ntd=outcome.objective_gross_margin_ntd,
        assumed_transfer_price_per_kwh=outcome.assumed_transfer_price_per_kwh,
        farm_ids=sorted(farm_id_set),
        customer_ids=sorted(cust_id_set),
        allocations=[
            ScenarioAllocationOut(
                wind_farm_id=a.wind_farm_id,
                customer_id=a.customer_id,
                allocated_mwh=a.allocated_mwh,
                margin_per_kwh=a.margin_per_kwh,
                has_contract=a.has_contract,
            )
            for a in outcome.allocations
        ],
        customer_targets=[
            OptCustomerTarget(
                customer_id=t.customer_id,
                re_target_mwh=t.re_target_mwh,
                allocated_mwh=t.allocated_mwh,
                re_shortfall_mwh=t.re_shortfall_mwh,
                re_target_met=t.re_target_met,
                sites_used=t.sites_used,
                site_shortfall=t.site_shortfall,
            )
            for t in outcome.customer_targets
        ],
        customer_summaries=[
            OptCustomerSummary(
                customer_id=s.customer_id,
                consumption_mwh=s.consumption_mwh,
                allocated_mwh=s.allocated_mwh,
                achieved_re_percent=s.achieved_re_percent,
            )
            for s in outcome.customer_summaries
        ],
        farm_summaries=[
            OptFarmSummary(
                wind_farm_id=s.farm_id,
                generated_mwh=s.generated_mwh,
                allocated_mwh=s.allocated_mwh,
                unallocated_mwh=s.unallocated_mwh,
            )
            for s in outcome.farm_summaries
        ],
    )
