"""Generate simulated multi-day 15-minute interval readings for a period (B6).

Writes ``IntervalReading`` rows for every wind farm (generation) and customer
(consumption), calibrated so each entity's monthly sum equals its existing
monthly total — the interval data carries real day-to-day texture (windy/calm
days, weekday/weekend load) without changing the energy basis. Clearly labelled
``data_source="mock-interval"``; real AMI lands in the same table.

Usage:
    python -m scripts.generate_interval_data --period 2024-01
"""

from __future__ import annotations

import argparse
import random
from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.ingestion.interval_synth import (
    SLOTS_PER_DAY,
    distribute_to_intervals,
    load_day_factors,
    solar_day_factors,
    wind_day_factors,
)
from app.matching.hourly_profile import generation_shape, load_shape, technology
from app.matching.interval_shape import days_in_period
from app.models import ConsumptionData, Customer, GenerationData, WindFarm
from app.models.interval import KIND_CONSUMPTION, KIND_GENERATION, IntervalReading
from app.services.matching_service import period_bounds

_DATA_SOURCE = "mock-interval"
# 24h continuous baseload barely dips on weekends; day-shift industries drop more.
_WEEKEND_FACTOR = {"半導體": 0.97}
_DEFAULT_WEEKEND = 0.82


def _sum_month(rows, key_attr: str, val_attr: str) -> dict[int, float]:
    out: dict[int, float] = {}
    for r in rows:
        k = getattr(r, key_attr)
        out[k] = out.get(k, 0.0) + getattr(r, val_attr)
    return out


def _rows_for(kind: str, ref_id: int, start, values: list[float]) -> list[dict]:
    base = datetime(start.year, start.month, start.day)
    mappings: list[dict] = []
    for i, energy in enumerate(values):
        d, j = divmod(i, SLOTS_PER_DAY)
        ts = base + timedelta(days=d, minutes=15 * j)
        mappings.append(
            {
                "kind": kind,
                "ref_id": ref_id,
                "ts": ts,
                "energy_mwh": energy,
                "data_source": _DATA_SOURCE,
            }
        )
    return mappings


def generate(db: Session, period: str, seed: int = 42) -> int:
    """(Re)generate interval readings for ``period``. Returns rows written."""
    start, end = period_bounds(period)
    ndays = days_in_period(start, end)
    dates = [start + timedelta(days=d) for d in range(ndays)]

    gen_totals = _sum_month(
        db.execute(
            select(GenerationData).where(
                GenerationData.period_start >= start,
                GenerationData.period_start <= end,
            )
        ).scalars(),
        "wind_farm_id",
        "generated_energy_mwh",
    )
    con_totals = _sum_month(
        db.execute(
            select(ConsumptionData).where(
                ConsumptionData.period_start >= start,
                ConsumptionData.period_start <= end,
            )
        ).scalars(),
        "customer_id",
        "consumed_energy_mwh",
    )

    # clear any prior interval rows for this window (idempotent re-seed)
    lo = datetime(start.year, start.month, start.day)
    hi = datetime(end.year, end.month, end.day) + timedelta(days=1)
    db.execute(
        delete(IntervalReading).where(IntervalReading.ts >= lo, IntervalReading.ts < hi)
    )

    mappings: list[dict] = []
    for f in db.execute(select(WindFarm).order_by(WindFarm.id)).scalars():
        total = gen_totals.get(f.id, 0.0)
        if total <= 0:
            continue
        tech = technology(f.farm_type)
        rng = random.Random(seed + f.id * 101)
        # solar varies with cloud cover, wind with windy/calm spells
        factors = (
            solar_day_factors(ndays, rng)
            if tech == "solar"
            else wind_day_factors(ndays, rng)
        )
        values = distribute_to_intervals(total, ndays, generation_shape(tech), factors)
        mappings += _rows_for(KIND_GENERATION, f.id, start, values)

    for c in db.execute(select(Customer).order_by(Customer.id)).scalars():
        total = con_totals.get(c.id, 0.0)
        if total <= 0:
            continue
        rng = random.Random(seed + c.id * 211)
        wf = _WEEKEND_FACTOR.get(c.industry or "", _DEFAULT_WEEKEND)
        factors = load_day_factors(dates, rng, wf)
        values = distribute_to_intervals(total, ndays, load_shape(c.industry), factors)
        mappings += _rows_for(KIND_CONSUMPTION, c.id, start, values)

    db.bulk_insert_mappings(IntervalReading, mappings)
    db.commit()
    return len(mappings)


def main() -> None:
    from app.db.session import SessionLocal

    ap = argparse.ArgumentParser()
    ap.add_argument("--period", default="2024-01")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    db = SessionLocal()
    try:
        n = generate(db, args.period, args.seed)
        print(f"interval rows written for {args.period}: {n}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
