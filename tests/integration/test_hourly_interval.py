"""Integration test: interval (B6) path of the hourly matching service."""

from __future__ import annotations

from datetime import date

import pytest

from app.models import GenerationData, WindFarm
from app.models.interval import KIND_GENERATION, IntervalReading
from app.services import hourly_matching_service as svc
from scripts.generate_interval_data import generate


def test_modeled_when_no_interval_data(seeded_db):
    res = svc.compute_hourly_outcome(seeded_db, "2024-01")
    assert res.source == "modeled"
    assert res.heatmap is None
    assert res.days == 1


def test_interval_source_and_heatmap_shape(seeded_db):
    written = generate(seeded_db, "2024-01")
    assert written > 0
    res = svc.compute_hourly_outcome(seeded_db, "2024-01")
    assert res.source == "interval"
    assert res.days == 31
    assert res.heatmap is not None
    assert len(res.heatmap.days) == 31
    assert len(res.heatmap.values) == 31
    assert all(len(row) == 24 for row in res.heatmap.values)


def test_interval_preserves_totals_and_cfe_below_paper(seeded_db):
    generate(seeded_db, "2024-01")
    res = svc.compute_hourly_outcome(seeded_db, "2024-01")
    # interval energy is calibrated to the monthly totals → Σ hourly == period total
    assert sum(res.consumption_by_hour) == pytest.approx(
        res.total_consumption_mwh, rel=1e-6
    )
    assert res.cfe_percent <= res.paper_re_percent + 1e-6
    assert 0.0 < res.cfe_percent < 100.0


def test_solar_interval_generation_is_zero_at_night(db):
    """A7: a solar site's synthesized interval data must sleep at night."""
    farm = WindFarm(
        code="S1", name="示範地面型光電", installed_capacity_mw=50, farm_type="solar"
    )
    db.add(farm)
    db.flush()
    db.add(
        GenerationData(
            wind_farm_id=farm.id,
            period_start=date(2024, 1, 1),
            period_end=date(2024, 1, 31),
            generated_energy_mwh=600.0,
        )
    )
    db.commit()

    generate(db, "2024-01")
    rows = list(
        db.query(IntervalReading).filter(IntervalReading.kind == KIND_GENERATION)
    )
    assert sum(r.energy_mwh for r in rows) == pytest.approx(600.0)
    night = [r for r in rows if r.ts.hour < 5 or r.ts.hour >= 20]
    assert night and all(r.energy_mwh == 0.0 for r in night)
    assert sum(r.energy_mwh for r in rows if r.ts.hour == 12) > 0.0


def test_heatmap_has_day_to_day_variation(seeded_db):
    generate(seeded_db, "2024-01")
    res = svc.compute_hourly_outcome(seeded_db, "2024-01")
    # pick an hour and confirm CFE differs across days (real interval texture)
    col = [row[8] for row in res.heatmap.values]
    assert max(col) - min(col) > 1.0
