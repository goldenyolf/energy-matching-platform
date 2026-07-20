from __future__ import annotations

from datetime import date

import pytest

from app.models import ConsumptionData, Contract, Customer, GenerationData, WindFarm
from app.models.enums import ContractStatus


@pytest.fixture()
def seeded(db):
    f = WindFarm(
        code="WF", name="F", installed_capacity_mw=100, feed_in_price_per_kwh=4.0
    )
    c = Customer(code="CU", company_name="X", re_target_percent=50.0)
    db.add_all([f, c])
    db.flush()
    db.add(
        GenerationData(
            wind_farm_id=f.id,
            period_start=date(2024, 1, 1),
            period_end=date(2024, 1, 31),
            generated_energy_mwh=300.0,
        )
    )
    db.add(
        ConsumptionData(
            customer_id=c.id,
            period_start=date(2024, 1, 1),
            period_end=date(2024, 1, 31),
            consumed_energy_mwh=500.0,
        )
    )
    db.add(
        Contract(
            contract_number="C1",
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


def test_trec_issue_ledger_retire(client, seeded):
    # issue
    resp = client.post("/api/v1/trecs/issue?period=2024-01")
    assert resp.status_code == 200
    led = resp.json()
    assert led["summary"]["total_batches"] >= 1
    assert led["summary"]["transferred_mwh"] > 0

    # ledger
    g = client.get("/api/v1/trecs?period=2024-01").json()
    assert g["summary"]["total_batches"] == led["summary"]["total_batches"]

    # retire the first batch
    bid = led["batches"][0]["id"]
    r = client.post(f"/api/v1/trecs/{bid}/retire")
    assert r.status_code == 200
    assert r.json()["status"] == "retired"

    after = client.get("/api/v1/trecs?period=2024-01").json()
    assert after["summary"]["retired_batches"] == 1


def test_trec_retire_unknown_404(client):
    assert client.post("/api/v1/trecs/999999/retire").status_code == 404
