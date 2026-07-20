"""Split a customer's consumption across its meters (電號/廠區), deterministic.

For each customer that has meters, every customer-level consumption row
(``meter_id IS NULL``) is replaced by one row per meter, weighted by the meter's
``annual_consumption_mwh`` share (equal split if none set). Period and time_slot
are preserved; the last meter absorbs rounding so the sum is exact. Idempotent:
rows already tagged with a meter_id are left alone.

Usage:
    python -m scripts.generate_meter_profiles
"""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models import ConsumptionData, Meter


def split_consumption_to_meters(db: Session) -> None:
    meters_by_customer: dict[int, list[Meter]] = defaultdict(list)
    for m in db.execute(select(Meter)).scalars():
        meters_by_customer[m.customer_id].append(m)

    for customer_id, meters in meters_by_customer.items():
        total_share = sum((m.annual_consumption_mwh or 0.0) for m in meters)
        rows = list(
            db.execute(
                select(ConsumptionData).where(
                    ConsumptionData.customer_id == customer_id,
                    ConsumptionData.meter_id.is_(None),
                )
            ).scalars()
        )
        for row in rows:
            running = 0.0
            for m in meters[:-1]:
                if total_share > 0:
                    share = (m.annual_consumption_mwh or 0.0) / total_share
                else:
                    share = 1.0 / len(meters)
                v = round(row.consumed_energy_mwh * share, 6)
                running += v
                db.add(
                    ConsumptionData(
                        customer_id=customer_id,
                        meter_id=m.id,
                        period_start=row.period_start,
                        period_end=row.period_end,
                        consumed_energy_mwh=v,
                        data_source=row.data_source,
                        time_slot=row.time_slot,
                    )
                )
            db.add(
                ConsumptionData(
                    customer_id=customer_id,
                    meter_id=meters[-1].id,
                    period_start=row.period_start,
                    period_end=row.period_end,
                    consumed_energy_mwh=round(row.consumed_energy_mwh - running, 6),
                    data_source=row.data_source,
                    time_slot=row.time_slot,
                )
            )
            db.delete(row)
    db.commit()


def main() -> None:
    db = SessionLocal()
    try:
        split_consumption_to_meters(db)
        print("split consumption across meters")
    finally:
        db.close()


if __name__ == "__main__":
    main()
