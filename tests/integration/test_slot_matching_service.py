"""Integration test: slot_matching_service against a seeded DB (slot rows)."""

from __future__ import annotations

from datetime import date

import pytest

from app.models import ConsumptionData, Contract, Customer, GenerationData, WindFarm
from app.models.enums import ContractStatus, TimeSlot
from app.services import slot_matching_service


@pytest.fixture()
def seeded(db):
    f = WindFarm(
        code="F1", name="F1", installed_capacity_mw=100, feed_in_price_per_kwh=4.0
    )
    cust = Customer(code="K1", company_name="K1", re_target_percent=100.0)
    db.add_all([f, cust])
    db.flush()
    for slot, gmwh, cmwh in [
        (TimeSlot.PEAK, 40.0, 50.0),
        (TimeSlot.HALF_PEAK, 30.0, 30.0),
        (TimeSlot.OFF_PEAK, 60.0, 20.0),
    ]:
        db.add(
            GenerationData(
                wind_farm_id=f.id,
                period_start=date(2024, 1, 1),
                period_end=date(2024, 1, 31),
                generated_energy_mwh=gmwh,
                time_slot=slot,
            )
        )
        db.add(
            ConsumptionData(
                customer_id=cust.id,
                period_start=date(2024, 1, 1),
                period_end=date(2024, 1, 31),
                consumed_energy_mwh=cmwh,
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


def test_compute_slot_outcome_structure(db, seeded):
    r = slot_matching_service.compute_slot_outcome(db, "2024-01")
    assert r.period == "2024-01"
    assert r.season == "non_summer"
    # peak: min(40,50)=40; half:min(30,30)=30; off:min(60,20)=20 -> total 90
    cs = {c.customer_id: c for c in r.customer_summaries}[seeded.id]
    assert cs.allocated_mwh == 90.0
    assert cs.consumption_mwh == 100.0
    assert cs.achieved_re_percent == 90.0
    # seller margin = 90 MWh * 1000 * (4.8 - 4.0) = 72000
    assert r.seller_gross_margin_ntd == pytest.approx(72000.0, abs=1.0)
    assert len(r.slot_breakdown) == 3


def test_compute_slot_outcome_empty_period(db, seeded):
    r = slot_matching_service.compute_slot_outcome(db, "2030-01")
    assert r.seller_gross_margin_ntd == 0.0
    assert (
        all(c.allocated_mwh == 0.0 for c in r.customer_summaries)
        or r.customer_summaries == []
    )
