from __future__ import annotations

from datetime import date

import pytest

from app.models import ConsumptionData, Contract, Customer, GenerationData, WindFarm
from app.models.enums import ContractStatus


@pytest.fixture()
def seeded(db):
    a = WindFarm(
        code="FA", name="A", installed_capacity_mw=100, feed_in_price_per_kwh=4.0
    )
    cheap = WindFarm(
        code="CHEAP", name="Cheap", installed_capacity_mw=100, feed_in_price_per_kwh=3.0
    )
    cust = Customer(code="CU", company_name="X", re_target_percent=50.0)
    db.add_all([a, cheap, cust])
    db.flush()
    for f, g in [(a, 200.0), (cheap, 250.0)]:
        db.add(
            GenerationData(
                wind_farm_id=f.id,
                period_start=date(2024, 1, 1),
                period_end=date(2024, 1, 31),
                generated_energy_mwh=g,
            )
        )
    db.add(
        ConsumptionData(
            customer_id=cust.id,
            period_start=date(2024, 1, 1),
            period_end=date(2024, 1, 31),
            consumed_energy_mwh=1000.0,
        )
    )
    db.add(
        Contract(
            contract_number="C-A",
            wind_farm_id=a.id,
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


def test_re_recommendations_endpoint(client, seeded):
    resp = client.get(
        f"/api/v1/analytics/re-recommendations?customer_id={seeded.id}&period=2024-01"
    )
    assert resp.status_code == 200
    b = resp.json()
    assert b["gap_mwh"] > 0
    assert b["recommendations"][0]["code"] == "CHEAP"  # cheapest first
    assert b["total_recommended_mwh"] <= b["gap_mwh"] + 1e-6


def test_re_recommendations_unknown_customer_404(client):
    resp = client.get(
        "/api/v1/analytics/re-recommendations?customer_id=999999&period=2024-01"
    )
    assert resp.status_code == 404
