from __future__ import annotations

from datetime import date

import pytest

from app.models import (
    ConsumptionData,
    Contract,
    Customer,
    GenerationData,
    Meter,
    WindFarm,
)
from app.models.enums import ContractStatus, TimeSlot


@pytest.fixture()
def seeded(db):
    f = WindFarm(
        code="WF-A", name="A", installed_capacity_mw=100, feed_in_price_per_kwh=4.0
    )
    c = Customer(code="CU-A", company_name="Alpha", re_target_percent=60.0)
    db.add_all([f, c])
    db.flush()
    tn = Meter(code="TN", customer_id=c.id, name="台南廠", re_target_percent=90.0)
    kh = Meter(code="KH", customer_id=c.id, name="高雄廠", re_target_percent=40.0)
    db.add_all([tn, kh])
    db.flush()
    for slot, g in [(TimeSlot.PEAK, 40.0), (TimeSlot.OFF_PEAK, 60.0)]:
        db.add(
            GenerationData(
                wind_farm_id=f.id,
                period_start=date(2024, 1, 1),
                period_end=date(2024, 1, 31),
                generated_energy_mwh=g,
                time_slot=slot,
            )
        )
    for m, tot in [(tn, 60.0), (kh, 40.0)]:
        for slot in (TimeSlot.PEAK, TimeSlot.OFF_PEAK):
            db.add(
                ConsumptionData(
                    customer_id=c.id,
                    meter_id=m.id,
                    period_start=date(2024, 1, 1),
                    period_end=date(2024, 1, 31),
                    consumed_energy_mwh=tot / 2,
                    time_slot=slot,
                )
            )
    db.add(
        Contract(
            contract_number="P1",
            wind_farm_id=f.id,
            customer_id=c.id,
            start_date=date(2024, 1, 1),
            end_date=date(2030, 12, 31),
            status=ContractStatus.ACTIVE,
            priority=1,
            contracted_percentage=100.0,
            price_per_kwh=5.0,
        )
    )
    db.commit()
    return c


def test_meter_breakdown_endpoint(client, seeded):
    resp = client.get(
        f"/api/v1/analytics/meter-breakdown?customer_id={seeded.id}&period=2024-01"
    )
    assert resp.status_code == 200
    b = resp.json()
    assert b["meter_count"] == 2
    assert sum(m["allocated_green_mwh"] for m in b["meters"]) == pytest.approx(
        b["total_green_mwh"], abs=1e-3
    )


def test_meter_breakdown_unknown_customer_404(client):
    resp = client.get(
        "/api/v1/analytics/meter-breakdown?customer_id=999999&period=2024-01"
    )
    assert resp.status_code == 404
