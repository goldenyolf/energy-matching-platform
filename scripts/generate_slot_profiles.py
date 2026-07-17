"""Split monthly generation/consumption rows into time-slot rows (deterministic).

Wind-typical slot ratios: generation skews to off-peak (night); consumption
skews to peak (industrial daytime). Slot rows replace the monthly row so the
mutual-exclusivity invariant holds (slot rows sum to the monthly total). The
last slot absorbs rounding so the sum is exact. Idempotent: rows already tagged
with a time_slot are left alone.

Usage:
    python -m scripts.generate_slot_profiles
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models import ConsumptionData, GenerationData
from app.models.enums import TimeSlot

GEN_RATIOS = {TimeSlot.PEAK: 0.25, TimeSlot.HALF_PEAK: 0.30, TimeSlot.OFF_PEAK: 0.45}
CON_RATIOS = {TimeSlot.PEAK: 0.40, TimeSlot.HALF_PEAK: 0.35, TimeSlot.OFF_PEAK: 0.25}
_ORDER = (TimeSlot.PEAK, TimeSlot.HALF_PEAK, TimeSlot.OFF_PEAK)


def _split_total(total: float, ratios: dict[TimeSlot, float]) -> dict[TimeSlot, float]:
    out: dict[TimeSlot, float] = {}
    running = 0.0
    for slot in _ORDER[:-1]:
        v = round(total * ratios[slot], 6)
        out[slot] = v
        running += v
    out[_ORDER[-1]] = round(total - running, 6)  # last absorbs rounding
    return out


def split_profiles(db: Session) -> None:
    for g in list(
        db.execute(
            select(GenerationData).where(GenerationData.time_slot.is_(None))
        ).scalars()
    ):
        for slot, mwh in _split_total(g.generated_energy_mwh, GEN_RATIOS).items():
            db.add(
                GenerationData(
                    wind_farm_id=g.wind_farm_id,
                    period_start=g.period_start,
                    period_end=g.period_end,
                    generated_energy_mwh=mwh,
                    data_source=g.data_source,
                    time_slot=slot,
                )
            )
        db.delete(g)
    for c in list(
        db.execute(
            select(ConsumptionData).where(ConsumptionData.time_slot.is_(None))
        ).scalars()
    ):
        for slot, mwh in _split_total(c.consumed_energy_mwh, CON_RATIOS).items():
            db.add(
                ConsumptionData(
                    customer_id=c.customer_id,
                    period_start=c.period_start,
                    period_end=c.period_end,
                    consumed_energy_mwh=mwh,
                    data_source=c.data_source,
                    time_slot=slot,
                )
            )
        db.delete(c)
    db.commit()


def main() -> None:
    db = SessionLocal()
    try:
        split_profiles(db)
        print("split monthly rows into time-slot profiles")
    finally:
        db.close()


if __name__ == "__main__":
    main()
