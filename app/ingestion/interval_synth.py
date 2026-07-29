"""Simulated multi-day 15-minute interval data (B6).

Builds clearly-labelled *simulated* interval energy that reads like real AMI /
SCADA: a within-day shape (from the typical-day profiles) modulated by per-day
variation (windy vs calm days; weekday vs weekend load), scaled so each entity's
monthly sum matches its existing monthly total — so switching the hourly view
from modeled to interval keeps the same energy basis, only the timing gets real
day-to-day texture. Real interval CSVs land in the same table and replace these.

Pure functions; the caller supplies a seeded ``random.Random`` for determinism.
"""

from __future__ import annotations

import random
from datetime import date

SLOTS_PER_HOUR = 4
SLOTS_PER_DAY = 24 * SLOTS_PER_HOUR  # 96


def distribute_to_intervals(
    monthly_total_mwh: float,
    ndays: int,
    base_hourly_shape: list[float],
    day_factors: list[float],
) -> list[float]:
    """Spread a monthly total over ``ndays × 96`` 15-minute slots.

    Each slot's raw weight is its hour's shape value × that day's factor; the
    whole series is then scaled so it sums exactly to ``monthly_total_mwh``.
    Returns a flat list ordered ``[day0 slot0..95, day1 slot0..95, ...]``.
    """
    raw: list[float] = []
    for d in range(ndays):
        f = day_factors[d]
        for j in range(SLOTS_PER_DAY):
            raw.append(base_hourly_shape[j // SLOTS_PER_HOUR] * f)
    total = sum(raw)
    if total <= 0:
        return [0.0] * (ndays * SLOTS_PER_DAY)
    k = monthly_total_mwh / total
    return [v * k for v in raw]


def wind_day_factors(ndays: int, rng: random.Random) -> list[float]:
    """Per-day wind multipliers with mild persistence (windy/calm spells)."""
    factors: list[float] = []
    level = 1.0
    for _ in range(ndays):
        # random walk around 1.0, clamped — nearby days correlate a little
        level = 0.6 * level + 0.4 * rng.uniform(0.5, 1.5)
        factors.append(max(0.35, min(1.7, level)))
    return factors


def solar_day_factors(ndays: int, rng: random.Random) -> list[float]:
    """Per-day solar multipliers driven by cloud cover (A7).

    Clear/cloudy spells persist a little like wind, but the swing is narrower:
    the sun shows up every day, clouds only take a bite out of it.
    """
    factors: list[float] = []
    level = 1.0
    for _ in range(ndays):
        level = 0.5 * level + 0.5 * rng.uniform(0.7, 1.25)
        factors.append(max(0.45, min(1.25, level)))
    return factors


def load_day_factors(
    dates: list[date], rng: random.Random, weekend_factor: float
) -> list[float]:
    """Per-day load multipliers: weekends scaled by ``weekend_factor``, plus
    small daily noise."""
    return [
        (weekend_factor if dt.weekday() >= 5 else 1.0) * rng.uniform(0.95, 1.05)
        for dt in dates
    ]
