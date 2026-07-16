"""API test for GET /api/v1/matching/optimize."""

from __future__ import annotations

from datetime import date

import pytest

from app.models import ConsumptionData, Contract, Customer, GenerationData, WindFarm
from app.models.enums import ContractStatus, GreenTargetType


@pytest.fixture()
def seeded(db):
    f1 = WindFarm(
        code="F1", name="F1", installed_capacity_mw=100, feed_in_price_per_kwh=4.0
    )
    f2 = WindFarm(
        code="F2", name="F2", installed_capacity_mw=100, feed_in_price_per_kwh=4.0
    )
    cust = Customer(
        code="K1",
        company_name="K1",
        re_target_percent=50.0,
        green_target_type=GreenTargetType.RE_PERCENT,
    )
    db.add_all([f1, f2, cust])
    db.flush()
    db.add_all(
        [
            GenerationData(
                wind_farm_id=f1.id,
                period_start=date(2024, 1, 1),
                period_end=date(2024, 1, 31),
                generated_energy_mwh=100.0,
            ),
            GenerationData(
                wind_farm_id=f2.id,
                period_start=date(2024, 1, 1),
                period_end=date(2024, 1, 31),
                generated_energy_mwh=100.0,
            ),
            ConsumptionData(
                customer_id=cust.id,
                period_start=date(2024, 1, 1),
                period_end=date(2024, 1, 31),
                consumed_energy_mwh=100.0,
            ),
            Contract(
                contract_number="C1",
                wind_farm_id=f1.id,
                customer_id=cust.id,
                start_date=date(2024, 1, 1),
                end_date=date(2024, 12, 31),
                status=ContractStatus.ACTIVE,
                priority=100,
                contracted_percentage=100.0,
                price_per_kwh=4.3,
            ),
            Contract(
                contract_number="C2",
                wind_farm_id=f2.id,
                customer_id=cust.id,
                start_date=date(2024, 1, 1),
                end_date=date(2024, 12, 31),
                status=ContractStatus.ACTIVE,
                priority=100,
                contracted_percentage=100.0,
                price_per_kwh=4.9,
            ),
        ]
    )
    db.commit()


def test_optimize_endpoint_returns_full_structure(client, seeded):
    resp = client.get("/api/v1/matching/optimize", params={"period": "2024-01"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["period"] == "2024-01"
    assert body["solver_status"] == "Optimal"
    assert "objective_gross_margin_ntd" in body
    assert len(body["customer_targets"]) == 1
    by_num = {a["contract_number"]: a["allocated_mwh"] for a in body["allocations"]}
    assert by_num["C2"] == 100.0


def test_optimize_endpoint_min_sites_query(client, seeded):
    resp = client.get(
        "/api/v1/matching/optimize", params={"period": "2024-01", "min_sites": 2}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["min_sites_per_customer"] == 2
    assert body["customer_targets"][0]["sites_used"] == 2


def test_optimize_endpoint_empty_period(client, seeded):
    resp = client.get("/api/v1/matching/optimize", params={"period": "2030-01"})
    assert resp.status_code == 200
    assert resp.json()["objective_gross_margin_ntd"] == 0.0
