"""Unified per-customer optimization evaluation (v1.1 + P4b).

Primary path (P4b): run the joint per-time-slot MILP for the period, focus one
customer, and derive seller/buyer economics, per-farm allocation, and the
time-slot breakdown from that single per-slot allocation — so every panel is
mutually consistent and time-slot values are exact/optimal (not derived). Falls
back to the monthly P3 optimizer when the period has no time-slot data. Supports
overriding the customer's RE target and using a single green transfer price.
Compute-only (no persistence).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.matching.engine import ContractInput, CustomerDemand, FarmSupply
from app.matching.optimizer import OptimizeOptions, optimize_period
from app.matching.slot_engine import SlotCustomerDemand, SlotFarmSupply
from app.matching.slot_optimizer import SlotOptimizeOptions, optimize_slots
from app.matching.tou import SLOT_ORDER, grey_price, season_of
from app.models import ConsumptionData, Contract, Customer, GenerationData, WindFarm
from app.models.enums import Season
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


def _load(db: Session) -> tuple[dict[int, WindFarm], dict[int, Contract]]:
    farms = {
        f.id: f for f in db.execute(select(WindFarm).order_by(WindFarm.id)).scalars()
    }
    contracts = {c.id: c for c in db.execute(select(Contract)).scalars()}
    return farms, contracts


def _has_slot_data(db: Session, start: date, end: date) -> bool:
    gen = db.execute(
        select(GenerationData.id).where(
            GenerationData.period_start >= start,
            GenerationData.period_start <= end,
            GenerationData.time_slot.is_not(None),
        )
    ).first()
    con = db.execute(
        select(ConsumptionData.id).where(
            ConsumptionData.period_start >= start,
            ConsumptionData.period_start <= end,
            ConsumptionData.time_slot.is_not(None),
        )
    ).first()
    return gen is not None and con is not None


def _build_result(
    *,
    customer: Customer,
    period: str,
    season: Season,
    solver_status: str,
    options: CustomerOptimizeOptions,
    procurement: float,
    revenue: float,
    green_mwh: float,
    consumption: float,
    used_default: bool,
    farm_out: list[FarmAllocationOut],
    slot_out: list[SlotRowOut],
    surplus: float,
) -> CustomerOptimizationResult:
    grey = settings.grey_price_per_kwh
    green_kwh = green_mwh * _KWH
    grey_mwh = max(0.0, consumption - green_mwh)
    total_kwh = consumption * _KWH
    gross_profit = revenue - procurement
    gross_margin = (gross_profit / revenue * 100.0) if revenue else 0.0
    re_percent = (green_mwh / consumption * 100.0) if consumption else 0.0
    avg_price = ((revenue + grey_mwh * _KWH * grey) / total_kwh) if total_kwh else 0.0
    added_cost = revenue - green_kwh * grey
    return CustomerOptimizationResult(
        period=period,
        season=season.value,
        solver_status=solver_status,
        customer_id=customer.id,
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
        time_mismatch_surplus_mwh=round(surplus, 3),
    )


def compute_customer_optimization(
    db: Session, customer_id: int, period: str, options: CustomerOptimizeOptions
) -> CustomerOptimizationResult:
    customer = db.get(Customer, customer_id)
    if customer is None:
        raise NotFoundError(f"customer {customer_id} not found")
    start, end = period_bounds(period)
    if _has_slot_data(db, start, end):
        return _compute_slot(db, customer, period, start, end, options)
    return _compute_monthly(db, customer, period, start, end, options)


# --------------------------------------------------------------------------- #
# P4b — joint per-time-slot MILP (primary)                                     #
# --------------------------------------------------------------------------- #
def _compute_slot(
    db: Session,
    customer: Customer,
    period: str,
    start: date,
    end: date,
    options: CustomerOptimizeOptions,
) -> CustomerOptimizationResult:
    focus_id = customer.id
    farms_orm, contracts_orm = _load(db)
    customers = {c.id: c for c in db.execute(select(Customer)).scalars()}

    slot_farms = [
        SlotFarmSupply(g.wind_farm_id, g.time_slot, g.generated_energy_mwh)
        for g in db.execute(
            select(GenerationData).where(
                GenerationData.period_start >= start,
                GenerationData.period_start <= end,
                GenerationData.time_slot.is_not(None),
            )
        ).scalars()
        if g.time_slot is not None
    ]
    slot_demands = []
    for c in db.execute(
        select(ConsumptionData).where(
            ConsumptionData.period_start >= start,
            ConsumptionData.period_start <= end,
            ConsumptionData.time_slot.is_not(None),
        )
    ).scalars():
        if c.time_slot is None:
            continue
        cust = customers.get(c.customer_id)
        slot_demands.append(
            SlotCustomerDemand(
                c.customer_id,
                c.time_slot,
                c.consumed_energy_mwh,
                green_target_type=(cust.green_target_type.value if cust else None),
                re_target_percent=(cust.re_target_percent if cust else None),
                target_energy_mwh=(cust.target_energy_mwh if cust else None),
            )
        )
    contracts = [_to_contract_input(c) for c in contracts_orm.values()]

    override = (
        {focus_id: options.re_target_percent}
        if options.re_target_percent is not None
        else None
    )
    outcome = optimize_slots(
        period,
        start,
        end,
        slot_farms,
        slot_demands,
        contracts,
        SlotOptimizeOptions(
            min_sites_per_customer=options.min_sites_per_customer,
            min_site_allocation_percent=options.min_site_allocation_percent,
            re_target_percent_override=override,
            default_feed_in_price_per_kwh=settings.default_feed_in_price_per_kwh,
        ),
    )
    season = season_of(start.month)
    default_feed = settings.default_feed_in_price_per_kwh

    def feed_of(farm_id: int) -> float:
        f = farms_orm.get(farm_id)
        v = f.feed_in_price_per_kwh if f else None
        return v if v is not None else default_feed

    def price_of(contract_id: int, farm_id: int) -> float:
        if options.transfer_price_per_kwh is not None:
            return options.transfer_price_per_kwh
        c = contracts_orm.get(contract_id)
        p = c.price_per_kwh if c else None
        return p if p is not None else feed_of(farm_id)

    focus = [
        a
        for a in outcome.allocations
        if a.customer_id == focus_id and a.allocated_mwh > 0
    ]
    used_default = False
    green_kwh = procurement = revenue = 0.0
    by_farm: dict[int, dict] = {}
    for a in focus:
        kwh = a.allocated_mwh * _KWH
        f = farms_orm.get(a.wind_farm_id)
        if f is None or f.feed_in_price_per_kwh is None:
            used_default = True
        green_kwh += kwh
        procurement += kwh * feed_of(a.wind_farm_id)
        revenue += kwh * price_of(a.contract_id, a.wind_farm_id)
        e = by_farm.setdefault(
            a.wind_farm_id,
            {"alloc": 0.0, "contract": a.contract_number, "reason": a.reason},
        )
        e["alloc"] += a.allocated_mwh
    green_mwh = green_kwh / _KWH

    total = {t.customer_id: t for t in outcome.customer_totals}.get(focus_id)
    consumption = total.consumption_mwh if total else 0.0
    surplus = total.re_shortfall_mwh if total else 0.0

    farm_out = [
        FarmAllocationOut(
            wind_farm_id=fid,
            wind_farm_code=(farms_orm[fid].code if fid in farms_orm else str(fid)),
            wind_farm_name=(farms_orm[fid].name if fid in farms_orm else ""),
            allocated_mwh=round(by_farm[fid]["alloc"], 6),
            share_percent=(
                round(by_farm[fid]["alloc"] / green_mwh * 100.0, 4)
                if green_mwh
                else 0.0
            ),
            contract_number=by_farm[fid]["contract"],
            reason=by_farm[fid]["reason"],
        )
        for fid in sorted(by_farm, key=lambda k: -by_farm[k]["alloc"])
    ]
    focus_slot = {r.slot: r for r in outcome.customer_slot if r.customer_id == focus_id}
    slot_out = [
        SlotRowOut(
            slot=s.value,
            grey_price_per_kwh=grey_price(season, s),
            consumption_mwh=(
                round(focus_slot[s].consumption_mwh, 6) if s in focus_slot else 0.0
            ),
            allocated_mwh=(
                round(focus_slot[s].allocated_mwh, 6) if s in focus_slot else 0.0
            ),
            re_percent=(round(focus_slot[s].re_percent, 4) if s in focus_slot else 0.0),
        )
        for s in SLOT_ORDER
    ]
    return _build_result(
        customer=customer,
        period=period,
        season=season,
        solver_status=outcome.solver_status,
        options=options,
        procurement=procurement,
        revenue=revenue,
        green_mwh=green_mwh,
        consumption=consumption,
        used_default=used_default,
        farm_out=farm_out,
        slot_out=slot_out,
        surplus=surplus,
    )


# --------------------------------------------------------------------------- #
# Fallback — monthly P3 optimizer (when no time-slot data)                     #
# --------------------------------------------------------------------------- #
def _to_contract_input(c: Contract) -> ContractInput:
    return ContractInput(
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


def _compute_monthly(
    db: Session,
    customer: Customer,
    period: str,
    start: date,
    end: date,
    options: CustomerOptimizeOptions,
) -> CustomerOptimizationResult:
    focus_id = customer.id
    gen = _sum_generation(db, start, end)
    con = _sum_consumption(db, start, end)
    farms_orm, contracts_orm = _load(db)

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
        override = c.id == focus_id and options.re_target_percent is not None
        demands.append(
            CustomerDemand(
                customer_id=c.id,
                consumed_mwh=con.get(c.id, 0.0),
                green_target_type=(
                    "re_percent" if override else c.green_target_type.value
                ),
                re_target_percent=(
                    options.re_target_percent if override else c.re_target_percent
                ),
                target_energy_mwh=(None if override else c.target_energy_mwh),
            )
        )
    contracts = [_to_contract_input(c) for c in contracts_orm.values()]

    outcome = optimize_period(
        period,
        start,
        end,
        farms,
        demands,
        contracts,
        OptimizeOptions(
            min_sites_per_customer=options.min_sites_per_customer,
            min_site_allocation_percent=options.min_site_allocation_percent,
            default_feed_in_price_per_kwh=settings.default_feed_in_price_per_kwh,
        ),
    )
    season = season_of(start.month)
    default_feed = settings.default_feed_in_price_per_kwh

    def feed_of(farm_id: int) -> float:
        f = farms_orm.get(farm_id)
        v = f.feed_in_price_per_kwh if f else None
        return v if v is not None else default_feed

    def price_of(contract_id: int, farm_id: int) -> float:
        if options.transfer_price_per_kwh is not None:
            return options.transfer_price_per_kwh
        c = contracts_orm.get(contract_id)
        p = c.price_per_kwh if c else None
        return p if p is not None else feed_of(farm_id)

    focus = [
        a
        for a in outcome.allocations
        if a.customer_id == focus_id and a.allocated_mwh > 0
    ]
    used_default = False
    green_kwh = procurement = revenue = 0.0
    by_farm: dict[int, dict] = {}
    for a in focus:
        kwh = a.allocated_mwh * _KWH
        f = farms_orm.get(a.wind_farm_id)
        if f is None or f.feed_in_price_per_kwh is None:
            used_default = True
        green_kwh += kwh
        procurement += kwh * feed_of(a.wind_farm_id)
        revenue += kwh * price_of(a.contract_id, a.wind_farm_id)
        e = by_farm.setdefault(
            a.wind_farm_id,
            {"alloc": 0.0, "contract": a.contract_number, "reason": a.reason},
        )
        e["alloc"] += a.allocated_mwh
    green_mwh = green_kwh / _KWH

    consumption = 0.0
    for cs in outcome.customer_summaries:
        if cs.customer_id == focus_id:
            consumption = cs.consumption_mwh

    farm_out = [
        FarmAllocationOut(
            wind_farm_id=fid,
            wind_farm_code=(farms_orm[fid].code if fid in farms_orm else str(fid)),
            wind_farm_name=(farms_orm[fid].name if fid in farms_orm else ""),
            allocated_mwh=round(by_farm[fid]["alloc"], 6),
            share_percent=(
                round(by_farm[fid]["alloc"] / green_mwh * 100.0, 4)
                if green_mwh
                else 0.0
            ),
            contract_number=by_farm[fid]["contract"],
            reason=by_farm[fid]["reason"],
        )
        for fid in sorted(by_farm, key=lambda k: -by_farm[k]["alloc"])
    ]

    # no time-slot data → empty slot breakdown (each slot 0)
    slot_out = [
        SlotRowOut(
            slot=s.value,
            grey_price_per_kwh=grey_price(season, s),
            consumption_mwh=0.0,
            allocated_mwh=0.0,
            re_percent=0.0,
        )
        for s in SLOT_ORDER
    ]
    tgt = customer.re_target_percent / 100.0 * consumption
    if options.re_target_percent is not None:
        tgt = options.re_target_percent / 100.0 * consumption
    surplus = max(0.0, min(consumption, tgt) - green_mwh)
    return _build_result(
        customer=customer,
        period=period,
        season=season,
        solver_status=outcome.solver_status,
        options=options,
        procurement=procurement,
        revenue=revenue,
        green_mwh=green_mwh,
        consumption=consumption,
        used_default=used_default,
        farm_out=farm_out,
        slot_out=slot_out,
        surplus=surplus,
    )
