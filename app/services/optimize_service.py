"""Economic-optimization service: load period data, solve, map to schema.

Pure read-side (compute-only, no persistence), mirroring evaluation service.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.matching.engine import ContractInput, CustomerDemand, FarmSupply
from app.matching.optimizer import OptimizeOptions, optimize_period
from app.models import Contract, Customer, WindFarm
from app.schemas.optimization import (
    OptAllocation,
    OptCustomerSummary,
    OptCustomerTarget,
    OptFarmSummary,
    OptimizationResult,
)
from app.services.matching_service import (
    _sum_consumption,
    _sum_generation,
    period_bounds,
)


def compute_optimized(
    db: Session, period: str, options: OptimizeOptions
) -> OptimizationResult:
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
    ]
    demands = [
        CustomerDemand(
            customer_id=c.id,
            consumed_mwh=con.get(c.id, 0.0),
            green_target_type=c.green_target_type.value,
            re_target_percent=c.re_target_percent,
            target_energy_mwh=c.target_energy_mwh,
        )
        for c in db.execute(select(Customer).order_by(Customer.id)).scalars()
    ]
    contracts = [
        ContractInput(
            contract_id=c.id,
            contract_number=c.contract_number,
            wind_farm_id=c.wind_farm_id,
            customer_id=c.customer_id,
            start_date=c.start_date,
            end_date=c.end_date,
            status=c.status.value,
            priority=c.priority,
            contracted_energy_mwh=c.contracted_energy_mwh,
            contracted_percentage=c.contracted_percentage,
            price_per_kwh=c.price_per_kwh,
        )
        for c in db.execute(select(Contract).order_by(Contract.id)).scalars()
    ]

    outcome = optimize_period(period, start, end, farms, demands, contracts, options)

    return OptimizationResult(
        period=period,
        solver_status=outcome.solver_status,
        objective_gross_margin_ntd=outcome.objective_gross_margin_ntd,
        min_sites_per_customer=options.min_sites_per_customer,
        min_site_allocation_percent=options.min_site_allocation_percent,
        allocations=[
            OptAllocation(
                contract_id=a.contract_id,
                contract_number=a.contract_number,
                wind_farm_id=a.wind_farm_id,
                customer_id=a.customer_id,
                allocated_mwh=a.allocated_mwh,
                contract_limit_mwh=a.contract_limit_mwh,
                reason=a.reason,
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
