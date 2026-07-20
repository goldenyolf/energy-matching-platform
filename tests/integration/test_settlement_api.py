from __future__ import annotations

from datetime import date

import pytest

from app.models import ConsumptionData, Contract, Customer, GenerationData, WindFarm
from app.models.enums import ContractStatus, TimeSlot


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


def test_settlement_endpoint_default(client, seeded):
    resp = client.get(
        f"/api/v1/analytics/settlement?customer_id={seeded.id}&period=2024-01"
    )
    assert resp.status_code == 200
    b = resp.json()
    t = b["totals"]
    assert t["customer_payable"] == round(
        t["green_transfer_cost"] + t["wheeling_fee"], 2
    )
    assert t["green_transfer_cost"] == pytest.approx(
        sum(s["green_cost"] for s in b["slots"]), abs=0.01
    )
    assert b["wheeling_fee_per_kwh"] == 0.1


def test_settlement_endpoint_override(client, seeded):
    resp = client.get(
        f"/api/v1/analytics/settlement?customer_id={seeded.id}&period=2024-01"
        "&transfer_price_per_kwh=6&wheeling_fee_per_kwh=0.2"
    )
    assert resp.status_code == 200
    b = resp.json()
    assert b["transfer_price_per_kwh"] == 6.0
    assert b["wheeling_fee_per_kwh"] == 0.2
    assert b["totals"]["wheeling_fee"] == round(
        b["totals"]["green_mwh"] * 1000 * 0.2, 2
    )


def test_settlement_endpoint_unknown_customer_404(client):
    resp = client.get("/api/v1/analytics/settlement?customer_id=999999&period=2024-01")
    assert resp.status_code == 404
