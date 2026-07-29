"""Tests for the simulated interval-data generator (B6)."""

from __future__ import annotations

import random
from datetime import date

import pytest

from app.ingestion import interval_synth as syn

SLOTS_PER_DAY = 96


def test_distribute_length_and_exact_total():
    shape = [1.0] * 24
    out = syn.distribute_to_intervals(
        1000.0, ndays=3, base_hourly_shape=shape, day_factors=[1.0, 1.0, 1.0]
    )
    assert len(out) == 3 * SLOTS_PER_DAY
    assert sum(out) == pytest.approx(1000.0)


def test_day_factor_scales_that_days_energy():
    shape = [1.0] * 24
    out = syn.distribute_to_intervals(
        900.0, ndays=2, base_hourly_shape=shape, day_factors=[1.0, 2.0]
    )
    day0 = sum(out[0:SLOTS_PER_DAY])
    day1 = sum(out[SLOTS_PER_DAY:])
    assert day1 == pytest.approx(2 * day0)
    assert day0 + day1 == pytest.approx(900.0)


def test_hour_shape_is_reflected_within_a_day():
    shape = [0.0] * 24
    shape[10] = 1.0  # all energy in hour 10
    out = syn.distribute_to_intervals(
        100.0, ndays=1, base_hourly_shape=shape, day_factors=[1.0]
    )
    hour10 = sum(out[10 * 4 : 10 * 4 + 4])
    assert hour10 == pytest.approx(100.0)
    assert sum(out[0:40]) == pytest.approx(0.0)


def test_load_day_factors_lower_on_weekends():
    # 2024-01-06 is a Saturday, 2024-01-08 a Monday.
    dates = [date(2024, 1, 6), date(2024, 1, 8)]
    rng = random.Random(1)
    f = syn.load_day_factors(dates, rng, weekend_factor=0.8)
    assert f[0] < f[1]  # Saturday factor below Monday


def test_wind_day_factors_vary_and_are_positive():
    rng = random.Random(1)
    f = syn.wind_day_factors(10, rng)
    assert len(f) == 10
    assert all(x > 0 for x in f)
    assert max(f) > min(f)  # day-to-day variation exists
