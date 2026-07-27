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
