"""Unified per-customer optimization: all panels derive from one allocation."""

from __future__ import annotations

from datetime import date

import pytest

from app.core.exceptions import NotFoundError
from app.models import ConsumptionData, Contract, Customer, GenerationData, WindFarm
from app.models.enums import ContractStatus, TimeSlot
from app.services.customer_optimization_service import (
    CustomerOptimizeOptions,
    compute_customer_optimization,
)


@pytest.fixture()
def seeded(db):
    f = WindFarm(
        code="F1", name="海能", installed_capacity_mw=100, feed_in_price_per_kwh=4.0
    )
    cust = Customer(code="K1", company_name="TSMC", re_target_percent=100.0)
    db.add_all([f, cust])
    db.flush()
    for slot, g, c in [
        (TimeSlot.PEAK, 40.0, 50.0),
        (TimeSlot.HALF_PEAK, 30.0, 30.0),
        (TimeSlot.OFF_PEAK, 60.0, 20.0),
    ]:
        db.add(
            GenerationData(
                wind_farm_id=f.id,
                period_start=date(2024, 1, 1),
                period_end=date(2024, 1, 31),
                generated_energy_mwh=g,
                time_slot=slot,
            )
        )
        db.add(
            ConsumptionData(
                customer_id=cust.id,
                period_start=date(2024, 1, 1),
                period_end=date(2024, 1, 31),
                consumed_energy_mwh=c,
                time_slot=slot,
            )
        )
    db.add(
        Contract(
            contract_number="C1",
            wind_farm_id=f.id,
            customer_id=cust.id,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
            status=ContractStatus.ACTIVE,
            priority=100,
            contracted_percentage=100.0,
            price_per_kwh=4.8,
        )
    )
    db.commit()
    return cust


def test_panels_are_mutually_consistent(db, seeded):
    r = compute_customer_optimization(
        db, seeded.id, "2024-01", CustomerOptimizeOptions()
    )
    # green_mwh equals the sum of per-farm allocations
    farm_sum = round(sum(a.allocated_mwh for a in r.allocations), 3)
    assert r.buyer.green_mwh == pytest.approx(farm_sum, abs=1e-3)
    # RE% = green / consumption
    assert r.buyer.re_percent == pytest.approx(
        r.buyer.green_mwh / r.buyer.total_consumption_mwh * 100.0, abs=1e-3
    )
    # gross_profit = revenue - procurement
    assert r.seller.gross_profit == pytest.approx(
        r.seller.sales_revenue - r.seller.procurement_cost, abs=1.0
    )
    # slot-matched green + time-mismatch surplus == total green; RE capped ≤ 100%
    slot_sum = round(sum(s.allocated_mwh for s in r.slot_breakdown), 3)
    assert slot_sum + r.time_mismatch_surplus_mwh == pytest.approx(
        r.buyer.green_mwh, abs=1e-2
    )
    for s in r.slot_breakdown:
        assert s.re_percent <= 100.0 + 1e-6
    assert r.season == "non_summer"
    assert len(r.slot_breakdown) == 3


def test_offpeak_surplus_is_flagged(db, seeded):
    # farm generates most at off-peak (60) but that customer uses little off-peak
    # (20), so some monthly green cannot land within the off-peak cap.
    r = compute_customer_optimization(
        db, seeded.id, "2024-01", CustomerOptimizeOptions()
    )
    assert r.time_mismatch_surplus_mwh > 0
    off = [s for s in r.slot_breakdown if s.slot == "off_peak"][0]
    assert off.re_percent <= 100.0 + 1e-6


def test_transfer_price_override(db, seeded):
    r = compute_customer_optimization(
        db,
        seeded.id,
        "2024-01",
        CustomerOptimizeOptions(transfer_price_per_kwh=6.0),
    )
    # revenue = green kwh * 6.0
    assert r.seller.sales_revenue == pytest.approx(
        r.buyer.green_mwh * 1000 * 6.0, abs=1.0
    )
    assert r.transfer_price_used == 6.0


def test_re_target_override_changes_target(db, seeded):
    r = compute_customer_optimization(
        db, seeded.id, "2024-01", CustomerOptimizeOptions(re_target_percent=50.0)
    )
    assert r.re_target_percent == 50.0


def test_unknown_customer_raises(db, seeded):
    with pytest.raises(NotFoundError):
        compute_customer_optimization(db, 999999, "2024-01", CustomerOptimizeOptions())


def test_empty_period_no_crash(db, seeded):
    r = compute_customer_optimization(
        db, seeded.id, "2030-01", CustomerOptimizeOptions()
    )
    assert r.buyer.green_mwh == 0.0
    assert r.allocations == []
