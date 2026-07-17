"""API test for GET /api/v1/matching/slots."""

from __future__ import annotations

from datetime import date

import pytest

from app.models import ConsumptionData, Contract, Customer, GenerationData, WindFarm
from app.models.enums import ContractStatus, TimeSlot


@pytest.fixture()
def seeded(db):
    f = WindFarm(
        code="F1", name="F1", installed_capacity_mw=100, feed_in_price_per_kwh=4.0
    )
    cust = Customer(code="K1", company_name="K1", re_target_percent=100.0)
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


def test_slots_endpoint(client, seeded):
    resp = client.get("/api/v1/matching/slots", params={"period": "2024-01"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["period"] == "2024-01"
    assert body["season"] == "non_summer"
    assert len(body["slot_breakdown"]) == 3
    assert body["customer_summaries"][0]["allocated_mwh"] == 90.0
    assert body["seller_gross_margin_ntd"] > 0


def test_slots_endpoint_empty(client, seeded):
    resp = client.get("/api/v1/matching/slots", params={"period": "2030-01"})
    assert resp.status_code == 200
    assert resp.json()["seller_gross_margin_ntd"] == 0.0
