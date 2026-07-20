"""Per-meter RE attainment via target-priority green distribution.

Analysis layer only: the customer's total green comes from the existing
customer-level optimization; here it is distributed across the customer's meters,
filling higher-target meters first so each 電號/廠區 shows a distinct RE%.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ConsumptionData, Meter
from app.schemas.meter import MeterBreakdown, MeterRow
from app.services.customer_optimization_service import (
    CustomerOptimizeOptions,
    compute_customer_optimization,
)
from app.services.matching_service import period_bounds


def compute_meter_breakdown(
    db: Session, customer_id: int, period: str
) -> MeterBreakdown:
    # 404s (NotFoundError) for an unknown customer, same as the other panels.
    co = compute_customer_optimization(
        db, customer_id, period, CustomerOptimizeOptions()
    )
    total_green = co.buyer.green_mwh

    meters = list(
        db.execute(select(Meter).where(Meter.customer_id == customer_id)).scalars()
    )
    if not meters:
        return MeterBreakdown(
            customer_id=co.customer_id,
            customer_code=co.customer_code,
            company_name=co.company_name,
            period=co.period,
            meter_count=0,
            total_consumption_mwh=round(co.buyer.total_consumption_mwh, 3),
            total_green_mwh=round(total_green, 3),
            customer_re_percent=round(co.buyer.re_percent, 4),
            meters_meeting_target=0,
            meters=[],
        )

    start, end = period_bounds(period)
    cons: dict[int, float] = {}
    for m in meters:
        cons[m.id] = sum(
            row.consumed_energy_mwh
            for row in db.execute(
                select(ConsumptionData).where(
                    ConsumptionData.meter_id == m.id,
                    ConsumptionData.period_start >= start,
                    ConsumptionData.period_start <= end,
                )
            ).scalars()
        )

    give: dict[int, float] = {m.id: 0.0 for m in meters}
    remaining = total_green
    # target pass: higher target first (tie: code asc)
    for m in sorted(meters, key=lambda x: (-x.re_target_percent, x.code)):
        target_energy = cons[m.id] * m.re_target_percent / 100.0
        g = min(remaining, target_energy)
        give[m.id] = g
        remaining -= g
    # leftover pass: top up toward the consumption cap, larger meters first
    if remaining > 1e-9:
        for m in sorted(meters, key=lambda x: -cons[x.id]):
            cap = cons[m.id] - give[m.id]
            g = min(cap, remaining)
            give[m.id] += g
            remaining -= g
            if remaining <= 1e-9:
                break

    rows: list[MeterRow] = []
    met = 0
    for m in sorted(meters, key=lambda x: (-x.re_target_percent, x.code)):
        alloc = give[m.id]
        c = cons[m.id]
        re = (alloc / c * 100.0) if c > 0 else 0.0
        is_met = re + 1e-9 >= m.re_target_percent and m.re_target_percent > 0
        if is_met:
            met += 1
        rows.append(
            MeterRow(
                meter_id=m.id,
                code=m.code,
                name=m.name,
                location=m.location,
                consumption_mwh=round(c, 3),
                allocated_green_mwh=round(alloc, 3),
                re_percent=round(re, 4),
                re_target_percent=m.re_target_percent,
                target_met=is_met,
            )
        )

    return MeterBreakdown(
        customer_id=co.customer_id,
        customer_code=co.customer_code,
        company_name=co.company_name,
        period=co.period,
        meter_count=len(meters),
        total_consumption_mwh=round(sum(cons.values()), 3),
        total_green_mwh=round(total_green, 3),
        customer_re_percent=round(co.buyer.re_percent, 4),
        meters_meeting_target=met,
        meters=rows,
    )
