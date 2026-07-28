"""Per-meter RE attainment via target-priority green distribution.

Analysis layer only: the customer's total green comes from the existing
customer-level optimization; here it is distributed across the customer's meters,
filling higher-target meters first so each 電號/廠區 shows a distinct RE%.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError
from app.models import ConsumptionData, Meter
from app.repositories.base import BaseRepository
from app.schemas.meter import MeterBreakdown, MeterCreate, MeterRow, MeterUpdate
from app.services.customer_optimization_service import (
    CustomerOptimizeOptions,
    compute_customer_optimization,
)
from app.services.matching_service import period_bounds


def _repo(db: Session) -> BaseRepository[Meter]:
    return BaseRepository(Meter, db)


def _tou_split(m: Meter, consumption_mwh: float) -> tuple[float, float, float] | None:
    """Split a meter's period consumption into (peak, half, off) MWh using its
    stored TOU load fields as proportions. 周六半尖峰 folds into 半尖峰 (the
    3-slot view). Returns None when the meter carries no TOU load data."""
    if (
        m.peak_kwh is None
        and m.half_peak_kwh is None
        and m.saturday_half_peak_kwh is None
        and m.off_peak_kwh is None
    ):
        return None
    peak = m.peak_kwh or 0.0
    half = (m.half_peak_kwh or 0.0) + (m.saturday_half_peak_kwh or 0.0)
    off = m.off_peak_kwh or 0.0
    total = peak + half + off
    if total <= 0:
        return None
    return (
        round(consumption_mwh * peak / total, 3),
        round(consumption_mwh * half / total, 3),
        round(consumption_mwh * off / total, 3),
    )


def create(db: Session, data: MeterCreate) -> Meter:
    repo = _repo(db)
    if repo.get_by(code=data.code):
        raise ConflictError(f"電號代碼 '{data.code}' 已存在")
    return repo.create(Meter(**data.model_dump()))


def get(db: Session, meter_id: int) -> Meter:
    meter = _repo(db).get(meter_id)
    if meter is None:
        raise NotFoundError(f"meter {meter_id} not found")
    return meter


def list_all(
    db: Session, *, customer_id: int | None = None, limit: int = 500, offset: int = 0
) -> list[Meter]:
    stmt = select(Meter).order_by(Meter.id)
    if customer_id is not None:
        stmt = stmt.where(Meter.customer_id == customer_id)
    return list(db.execute(stmt.offset(offset).limit(limit)).scalars())


def update(db: Session, meter_id: int, data: MeterUpdate) -> Meter:
    meter = get(db, meter_id)
    return _repo(db).update(meter, data.model_dump(exclude_unset=True))


def delete(db: Session, meter_id: int) -> None:
    """Delete a meter, refusing if consumption records still reference it."""
    meter = get(db, meter_id)
    used = db.scalar(
        select(func.count())
        .select_from(ConsumptionData)
        .where(ConsumptionData.meter_id == meter_id)
    )
    if used:
        raise ConflictError(f"此電號尚有 {used} 筆用電資料,請先移除關聯資料後再刪除。")
    _repo(db).delete(meter)


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
    # Per-電號 consumption. When the meters carry stored load data (total_kwh),
    # each meter's share of the customer's period consumption follows its
    # total_kwh — so editing a meter's load fields changes its 用電/RE here.
    # Otherwise fall back to the measured monthly ConsumptionData rows.
    cons: dict[int, float] = {}
    total_load_kwh = sum((m.total_kwh or 0.0) for m in meters)
    if total_load_kwh > 0:
        customer_total = co.buyer.total_consumption_mwh
        ordered = sorted(meters, key=lambda x: x.id)
        assigned = 0.0
        for i, m in enumerate(ordered):
            if i == len(ordered) - 1:  # last meter absorbs rounding → exact Σ
                cons[m.id] = round(customer_total - assigned, 6)
            else:
                v = round(customer_total * (m.total_kwh or 0.0) / total_load_kwh, 6)
                cons[m.id] = v
                assigned += v
    else:
        # One grouped query for all meters (avoids a SELECT per meter).
        summed = db.execute(
            select(
                ConsumptionData.meter_id,
                func.sum(ConsumptionData.consumed_energy_mwh),
            )
            .where(
                ConsumptionData.meter_id.in_([m.id for m in meters]),
                ConsumptionData.period_start >= start,
                ConsumptionData.period_start <= end,
            )
            .group_by(ConsumptionData.meter_id)
        ).all()
        by_meter = {mid: float(total or 0.0) for mid, total in summed}
        for m in meters:
            cons[m.id] = by_meter.get(m.id, 0.0)

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
        tou = _tou_split(m, c)
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
                peak_mwh=tou[0] if tou else None,
                half_peak_mwh=tou[1] if tou else None,
                off_peak_mwh=tou[2] if tou else None,
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
