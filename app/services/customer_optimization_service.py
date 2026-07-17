"""Unified per-customer optimization evaluation (v1.1).

Runs the P3 MILP optimizer once for the period, focuses on one customer, and
derives seller/buyer economics, per-farm allocation, and a time-slot breakdown
from that single allocation — so all panels are mutually consistent. Supports
overriding the customer's RE target and using a single green transfer price.
Compute-only (no persistence).
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.matching.engine import ContractInput, CustomerDemand, FarmSupply
from app.matching.optimizer import OptimizeOptions, optimize_period
from app.matching.tou import SLOT_ORDER, grey_price, season_of
from app.models import ConsumptionData, Contract, Customer, GenerationData, WindFarm
from app.schemas.customer_optimization import (
    BuyerSide,
    CustomerOptimizationResult,
    FarmAllocationOut,
    SellerSide,
    SlotRowOut,
)
from app.services.matching_service import (
    _sum_consumption,
    _sum_generation,
    period_bounds,
)

_KWH = 1000.0


@dataclass
class CustomerOptimizeOptions:
    min_sites_per_customer: int = 0
    min_site_allocation_percent: float = 0.0
    re_target_percent: float | None = None
    transfer_price_per_kwh: float | None = None


def compute_customer_optimization(
    db: Session, customer_id: int, period: str, options: CustomerOptimizeOptions
) -> CustomerOptimizationResult:
    customer = db.get(Customer, customer_id)
    if customer is None:
        raise NotFoundError(f"customer {customer_id} not found")

    start, end = period_bounds(period)
    gen = _sum_generation(db, start, end)
    con = _sum_consumption(db, start, end)
    farms_orm = {
        f.id: f for f in db.execute(select(WindFarm).order_by(WindFarm.id)).scalars()
    }
    contracts_orm = {c.id: c for c in db.execute(select(Contract)).scalars()}

    farms = [
        FarmSupply(
            farm_id=f.id,
            generated_mwh=gen.get(f.id, 0.0),
            feed_in_price_per_kwh=f.feed_in_price_per_kwh,
        )
        for f in farms_orm.values()
    ]
    demands = []
    for c in db.execute(select(Customer).order_by(Customer.id)).scalars():
        if c.id == customer_id and options.re_target_percent is not None:
            demands.append(
                CustomerDemand(
                    customer_id=c.id,
                    consumed_mwh=con.get(c.id, 0.0),
                    green_target_type="re_percent",
                    re_target_percent=options.re_target_percent,
                    target_energy_mwh=None,
                )
            )
        else:
            demands.append(
                CustomerDemand(
                    customer_id=c.id,
                    consumed_mwh=con.get(c.id, 0.0),
                    green_target_type=c.green_target_type.value,
                    re_target_percent=c.re_target_percent,
                    target_energy_mwh=c.target_energy_mwh,
                )
            )
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
        for c in contracts_orm.values()
    ]

    opts = OptimizeOptions(
        min_sites_per_customer=options.min_sites_per_customer,
        min_site_allocation_percent=options.min_site_allocation_percent,
        default_feed_in_price_per_kwh=settings.default_feed_in_price_per_kwh,
    )
    outcome = optimize_period(period, start, end, farms, demands, contracts, opts)

    grey = settings.grey_price_per_kwh
    default_feed = settings.default_feed_in_price_per_kwh
    focus = [
        a
        for a in outcome.allocations
        if a.customer_id == customer_id and a.allocated_mwh > 0
    ]

    def feed_of(farm_id: int) -> float:
        f = farms_orm.get(farm_id)
        v = f.feed_in_price_per_kwh if f else None
        return v if v is not None else default_feed

    def price_of(alloc) -> float:
        if options.transfer_price_per_kwh is not None:
            return options.transfer_price_per_kwh
        c = contracts_orm.get(alloc.contract_id)
        p = c.price_per_kwh if c else None
        return p if p is not None else feed_of(alloc.wind_farm_id)

    used_default = False
    green_kwh = procurement = revenue = 0.0
    for a in focus:
        kwh = a.allocated_mwh * _KWH
        f = farms_orm.get(a.wind_farm_id)
        if f is None or f.feed_in_price_per_kwh is None:
            used_default = True
        green_kwh += kwh
        procurement += kwh * feed_of(a.wind_farm_id)
        revenue += kwh * price_of(a)

    consumption = 0.0
    for cs in outcome.customer_summaries:
        if cs.customer_id == customer_id:
            consumption = cs.consumption_mwh
    green_mwh = green_kwh / _KWH
    grey_mwh = max(0.0, consumption - green_mwh)
    total_kwh = consumption * _KWH
    gross_profit = revenue - procurement
    gross_margin = (gross_profit / revenue * 100.0) if revenue else 0.0
    re_percent = (green_mwh / consumption * 100.0) if consumption else 0.0
    avg_price = ((revenue + grey_mwh * _KWH * grey) / total_kwh) if total_kwh else 0.0
    added_cost = revenue - green_kwh * grey

    # per-farm aggregate for the focus customer
    by_farm: dict[int, dict] = {}
    for a in focus:
        e = by_farm.setdefault(
            a.wind_farm_id,
            {"alloc": 0.0, "contract": a.contract_number, "reason": a.reason},
        )
        e["alloc"] += a.allocated_mwh
    farm_out = []
    for fid in sorted(by_farm, key=lambda k: -by_farm[k]["alloc"]):
        e = by_farm[fid]
        f = farms_orm.get(fid)
        farm_out.append(
            FarmAllocationOut(
                wind_farm_id=fid,
                wind_farm_code=(f.code if f else str(fid)),
                wind_farm_name=(f.name if f else ""),
                allocated_mwh=round(e["alloc"], 6),
                share_percent=(
                    round(e["alloc"] / green_mwh * 100.0, 4) if green_mwh else 0.0
                ),
                contract_number=e["contract"],
                reason=e["reason"],
            )
        )

    # time-slot breakdown derived from the same monthly allocation
    season = season_of(start.month)
    slot_gen: dict[tuple, float] = {}
    for g in db.execute(
        select(GenerationData).where(
            GenerationData.period_start >= start,
            GenerationData.period_start <= end,
            GenerationData.time_slot.is_not(None),
        )
    ).scalars():
        slot_gen[(g.wind_farm_id, g.time_slot)] = (
            slot_gen.get((g.wind_farm_id, g.time_slot), 0.0) + g.generated_energy_mwh
        )
    slot_con: dict = {}
    for row in db.execute(
        select(ConsumptionData).where(
            ConsumptionData.customer_id == customer_id,
            ConsumptionData.period_start >= start,
            ConsumptionData.period_start <= end,
            ConsumptionData.time_slot.is_not(None),
        )
    ).scalars():
        slot_con[row.time_slot] = (
            slot_con.get(row.time_slot, 0.0) + row.consumed_energy_mwh
        )

    green_slot = dict.fromkeys(SLOT_ORDER, 0.0)
    for fid, e in by_farm.items():
        totals = [slot_gen.get((fid, s), 0.0) for s in SLOT_ORDER]
        tot = sum(totals)
        for i, s in enumerate(SLOT_ORDER):
            ratio = (totals[i] / tot) if tot > 0 else (1.0 / len(SLOT_ORDER))
            green_slot[s] += e["alloc"] * ratio

    slot_out = []
    slot_matched = 0.0
    for s in SLOT_ORDER:
        cons = slot_con.get(s, 0.0)
        # A slot cannot receive more green than it consumes (patent eq.5): green
        # distributed to a slot by generation share is capped at that slot's use.
        gr = min(green_slot[s], cons)
        slot_matched += gr
        slot_out.append(
            SlotRowOut(
                slot=s.value,
                grey_price_per_kwh=grey_price(season, s),
                consumption_mwh=round(cons, 6),
                allocated_mwh=round(gr, 6),
                re_percent=round(gr / cons * 100.0, 4) if cons else 0.0,
            )
        )
    # Monthly green that cannot land within per-slot caps (off-peak wind surplus)
    time_mismatch_surplus = max(0.0, green_mwh - slot_matched)

    return CustomerOptimizationResult(
        period=period,
        season=season.value,
        solver_status=outcome.solver_status,
        customer_id=customer_id,
        customer_code=customer.code,
        company_name=customer.company_name,
        re_target_percent=(
            options.re_target_percent
            if options.re_target_percent is not None
            else customer.re_target_percent
        ),
        transfer_price_used=options.transfer_price_per_kwh,
        min_sites_per_customer=options.min_sites_per_customer,
        min_site_allocation_percent=options.min_site_allocation_percent,
        used_default_feed_in_price=used_default,
        seller=SellerSide(
            procurement_cost=round(procurement, 2),
            sales_revenue=round(revenue, 2),
            gross_profit=round(gross_profit, 2),
            gross_margin_percent=round(gross_margin, 4),
        ),
        buyer=BuyerSide(
            total_consumption_mwh=round(consumption, 3),
            green_mwh=round(green_mwh, 3),
            grey_mwh=round(grey_mwh, 3),
            re_percent=round(re_percent, 4),
            avg_price_per_kwh=round(avg_price, 4),
            added_cost=round(added_cost, 2),
        ),
        allocations=farm_out,
        slot_breakdown=slot_out,
        time_mismatch_surplus_mwh=round(time_mismatch_surplus, 3),
    )
