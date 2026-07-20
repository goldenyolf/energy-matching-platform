from __future__ import annotations

from datetime import date

import pytest

from app.models import ConsumptionData, Contract, Customer, GenerationData, WindFarm
from app.models.enums import ContractStatus, TimeSlot
from app.services.settlement_service import SettlementOptions, compute_settlement


@pytest.fixture()
def seeded(db):
    f = WindFarm(
        code="WF-A", name="海能", installed_capacity_mw=100, feed_in_price_per_kwh=4.0
    )
    cust = Customer(code="CU-A", company_name="Alpha", re_target_percent=50.0)
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
            contract_number="PPA-A",
            wind_farm_id=f.id,
            customer_id=cust.id,
            start_date=date(2024, 1, 1),
            end_date=date(2030, 12, 31),
            status=ContractStatus.ACTIVE,
            priority=1,
            contracted_percentage=100.0,
            price_per_kwh=5.0,
        )
    )
    db.commit()
    return cust


def test_settlement_totals_consistent(db, seeded):
    r = compute_settlement(
        db,
        seeded.id,
        "2024-01",
        SettlementOptions(transfer_price_per_kwh=None, wheeling_fee_per_kwh=0.1),
    )
    t = r.totals
    # per-slot green cost sums to the green transfer cost (uses real slot data)
    assert t.green_transfer_cost == pytest.approx(
        sum(s.green_cost for s in r.slots), abs=0.01
    )
    assert any(s.green_mwh > 0 for s in r.slots)  # slot path, not zero-filled
    assert t.wheeling_fee == round(t.green_mwh * 1000 * 0.1, 2)
    assert t.customer_payable == round(t.green_transfer_cost + t.wheeling_fee, 2)
    assert t.retailer_margin == round(
        t.green_transfer_cost - t.farm_receivable - t.wheeling_fee, 2
    )
    assert t.carbon_avoided_tco2e == round(t.green_mwh * 0.494, 2)
    assert r.transfer_price_per_kwh > 0
    assert r.farms and r.farms[0].wind_farm_code == "WF-A"


def test_settlement_override_wheeling(db, seeded):
    r = compute_settlement(
        db,
        seeded.id,
        "2024-01",
        SettlementOptions(transfer_price_per_kwh=6.0, wheeling_fee_per_kwh=0.2),
    )
    assert r.wheeling_fee_per_kwh == 0.2
    assert r.transfer_price_per_kwh == 6.0
    assert r.totals.wheeling_fee == round(r.totals.green_mwh * 1000 * 0.2, 2)
