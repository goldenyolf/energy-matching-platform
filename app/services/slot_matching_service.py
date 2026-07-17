"""Time-slot matching service: load slot rows, match, compute TOU economics.

Compute-only (no persistence), mirroring evaluation / optimize services.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.matching.engine import ContractInput
from app.matching.slot_engine import (
    SlotCustomerDemand,
    SlotFarmSupply,
    match_slots,
)
from app.matching.tou import grey_price
from app.models import ConsumptionData, Contract, GenerationData, WindFarm
from app.schemas.slot_matching import (
    BuyerSide,
    CustomerSummaryOut,
    FarmSummaryOut,
    SlotAllocationOut,
    SlotBreakdown,
    SlotMatchingResult,
)
from app.services.matching_service import period_bounds

_KWH = 1000.0


def compute_slot_outcome(db: Session, period: str) -> SlotMatchingResult:
    start, end = period_bounds(period)

    gen_rows = db.execute(
        select(GenerationData).where(
            GenerationData.period_start >= start,
            GenerationData.period_start <= end,
            GenerationData.time_slot.is_not(None),
        )
    ).scalars()
    farms = [
        SlotFarmSupply(g.wind_farm_id, g.time_slot, g.generated_energy_mwh)
        for g in gen_rows
        if g.time_slot is not None
    ]
    con_rows = db.execute(
        select(ConsumptionData).where(
            ConsumptionData.period_start >= start,
            ConsumptionData.period_start <= end,
            ConsumptionData.time_slot.is_not(None),
        )
    ).scalars()
    demands = [
        SlotCustomerDemand(c.customer_id, c.time_slot, c.consumed_energy_mwh)
        for c in con_rows
        if c.time_slot is not None
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

    outcome = match_slots(period, start, end, farms, demands, contracts)

    feedin = {
        f.id: f.feed_in_price_per_kwh for f in db.execute(select(WindFarm)).scalars()
    }
    price = {
        c.id: (c.price_per_kwh or 0.0) for c in db.execute(select(Contract)).scalars()
    }
    default_feed = settings.default_feed_in_price_per_kwh

    # seller gross margin (sum over slot allocations)
    seller_margin = 0.0
    for a in outcome.allocations:
        if a.allocated_mwh <= 0:
            continue
        feed = feedin.get(a.wind_farm_id)
        feed = feed if feed is not None else default_feed
        seller_margin += a.allocated_mwh * _KWH * (price.get(a.contract_id, 0.0) - feed)

    # buyer TOU economics
    total_kwh = sum(c.consumption_mwh for c in outcome.customer_summaries) * _KWH
    green_kwh = sum(c.allocated_mwh for c in outcome.customer_summaries) * _KWH

    # green cost & added cost: per allocation, using that slot's grey price
    green_cost = 0.0
    added_cost = 0.0
    for a in outcome.allocations:
        if a.allocated_mwh <= 0:
            continue
        kwh = a.allocated_mwh * _KWH
        p = price.get(a.contract_id, 0.0)
        g = grey_price(outcome.season, a.slot)
        green_cost += kwh * p
        added_cost += kwh * (p - g)

    # grey cost: per slot, unmatched consumption priced at that slot's grey price
    grey_cost = 0.0
    for sub in outcome.slot_subtotals:
        g = grey_price(outcome.season, sub.slot)
        slot_green = sum(cs.allocated_mwh for cs in sub.customer_summaries) * _KWH
        slot_consumed = sum(cs.consumption_mwh for cs in sub.customer_summaries) * _KWH
        grey_cost += max(0.0, slot_consumed - slot_green) * g

    re_percent = (green_kwh / total_kwh * 100.0) if total_kwh else 0.0
    avg_price = ((green_cost + grey_cost) / total_kwh) if total_kwh else 0.0

    return SlotMatchingResult(
        period=period,
        season=outcome.season.value,
        allocations=[
            SlotAllocationOut(
                contract_id=a.contract_id,
                contract_number=a.contract_number,
                wind_farm_id=a.wind_farm_id,
                customer_id=a.customer_id,
                slot=a.slot.value,
                allocated_mwh=a.allocated_mwh,
                reason=a.reason,
            )
            for a in outcome.allocations
        ],
        customer_summaries=[
            CustomerSummaryOut(
                customer_id=s.customer_id,
                consumption_mwh=s.consumption_mwh,
                allocated_mwh=s.allocated_mwh,
                achieved_re_percent=s.achieved_re_percent,
            )
            for s in outcome.customer_summaries
        ],
        farm_summaries=[
            FarmSummaryOut(
                wind_farm_id=s.farm_id,
                generated_mwh=s.generated_mwh,
                allocated_mwh=s.allocated_mwh,
                unallocated_mwh=s.unallocated_mwh,
            )
            for s in outcome.farm_summaries
        ],
        slot_breakdown=[
            SlotBreakdown(
                slot=sub.slot.value,
                grey_price_per_kwh=grey_price(outcome.season, sub.slot),
                customer_summaries=[
                    CustomerSummaryOut(
                        customer_id=cs.customer_id,
                        consumption_mwh=cs.consumption_mwh,
                        allocated_mwh=cs.allocated_mwh,
                        achieved_re_percent=cs.achieved_re_percent,
                    )
                    for cs in sub.customer_summaries
                ],
                farm_summaries=[
                    FarmSummaryOut(
                        wind_farm_id=fs.farm_id,
                        generated_mwh=fs.generated_mwh,
                        allocated_mwh=fs.allocated_mwh,
                        unallocated_mwh=fs.unallocated_mwh,
                    )
                    for fs in sub.farm_summaries
                ],
            )
            for sub in outcome.slot_subtotals
        ],
        seller_gross_margin_ntd=round(seller_margin, 6),
        buyer=BuyerSide(
            re_percent=round(re_percent, 4),
            avg_price_per_kwh=round(avg_price, 4),
            added_cost=round(added_cost, 2),
        ),
    )
