"""Investment analysis (ROI / payback) service tests."""

from __future__ import annotations

from datetime import date

import pytest

from app.models import GenerationData, WindFarm
from app.services.investment_service import compute_investment


def test_farm_and_total_investment(db):
    f = WindFarm(
        code="F1", name="海能", installed_capacity_mw=100, feed_in_price_per_kwh=4.0
    )
    db.add(f)
    db.flush()
    # 400,000 MWh/yr — a realistic ~45% capacity factor for 100 MW offshore
    db.add(
        GenerationData(
            wind_farm_id=f.id,
            period_start=date(2024, 1, 1),
            period_end=date(2024, 1, 31),
            generated_energy_mwh=240_000.0,
        )
    )
    db.add(
        GenerationData(
            wind_farm_id=f.id,
            period_start=date(2024, 2, 1),
            period_end=date(2024, 2, 28),
            generated_energy_mwh=160_000.0,
        )
    )
    db.commit()

    r = compute_investment(db, capex_per_mw=80_000_000.0, om_rate_percent=2.0)
    inv = r.farms[0]
    exp_revenue = 400_000.0 * 1000 * 4.0  # kWh × NTD/kWh → 1.6e9
    exp_capex = 100.0 * 80_000_000.0  # 8e9
    exp_om = exp_capex * 0.02  # 1.6e8
    exp_net = exp_revenue - exp_om  # 1.44e9
    assert inv.capacity_mw == 100.0
    assert inv.annual_generation_mwh == 400_000.0
    assert inv.annual_revenue == pytest.approx(exp_revenue)
    assert inv.capex == pytest.approx(exp_capex)
    assert inv.annual_om == pytest.approx(exp_om)
    assert inv.annual_net == pytest.approx(exp_net)
    assert inv.roi_percent == pytest.approx(exp_net / exp_capex * 100.0)  # 18.0
    assert inv.payback_years == pytest.approx(exp_capex / exp_net, abs=0.01)  # ~5.56
    # portfolio total mirrors the single farm
    assert r.total.capex == pytest.approx(inv.capex)
    assert r.total.annual_net == pytest.approx(inv.annual_net)
    assert r.capex_per_mw == 80_000_000.0
    assert r.om_rate_percent == 2.0


def test_payback_none_when_unprofitable(db):
    f = WindFarm(
        code="F2", name="小場", installed_capacity_mw=1000, feed_in_price_per_kwh=0.1
    )
    db.add(f)
    db.flush()
    db.add(
        GenerationData(
            wind_farm_id=f.id,
            period_start=date(2024, 1, 1),
            period_end=date(2024, 1, 31),
            generated_energy_mwh=1.0,
        )
    )
    db.commit()
    r = compute_investment(db, capex_per_mw=80_000_000.0, om_rate_percent=5.0)
    assert r.farms[0].annual_net < 0
    assert r.farms[0].payback_years is None
    assert r.total.payback_years is None


def test_uses_default_feed_in_when_missing(db):
    f = WindFarm(code="F3", name="無價場", installed_capacity_mw=10)  # feed_in None
    db.add(f)
    db.flush()
    db.add(
        GenerationData(
            wind_farm_id=f.id,
            period_start=date(2024, 1, 1),
            period_end=date(2024, 1, 31),
            generated_energy_mwh=100.0,
        )
    )
    db.commit()
    r = compute_investment(db, capex_per_mw=80_000_000.0, om_rate_percent=2.0)
    # revenue uses the default feed-in price (4.0) when the farm has none
    assert r.farms[0].selling_price_per_kwh == 4.0
