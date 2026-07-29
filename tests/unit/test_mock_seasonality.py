"""Technology-aware monthly seasonality in the deterministic mock generator (A7).

Wind is winter-strong (NE monsoon); solar is summer-strong. Opposite seasons is
half of 風光互補 — the other half is the within-day shape (hourly_profile).
"""

from __future__ import annotations

import pytest

from app.ingestion.sources import MockDataGenerator


def _monthly(rows: list[dict]) -> list[float]:
    return [float(r["generated_energy_mwh"]) for r in rows]


def test_solar_rows_preserve_the_annual_total():
    gen = MockDataGenerator(year=2024)
    rows = gen.generation_rows("SF-DEMO", 100_000, technology="solar")
    assert len(rows) == 12
    assert sum(_monthly(rows)) == pytest.approx(100_000, rel=1e-4)


def test_solar_is_summer_strong_while_wind_is_winter_strong():
    gen = MockDataGenerator(year=2024)
    solar = _monthly(gen.generation_rows("SF-DEMO", 120_000, technology="solar"))
    wind = _monthly(gen.generation_rows("WF-DEMO", 120_000, technology="wind"))
    jan, jul = 0, 6
    assert solar[jul] > solar[jan]
    assert wind[jan] > wind[jul]


def test_generation_rows_default_to_the_wind_profile():
    gen = MockDataGenerator(year=2024)
    default = _monthly(gen.generation_rows("WF-DEMO", 120_000))
    wind = _monthly(gen.generation_rows("WF-DEMO", 120_000, technology="wind"))
    assert default == wind
