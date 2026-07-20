from __future__ import annotations

from datetime import date, timedelta

from app.models import Contract, Customer, WindFarm
from app.models.enums import ContractStatus


def _seed_near_expiry(db):
    f = WindFarm(
        code="WF-A", name="海能", installed_capacity_mw=100, feed_in_price_per_kwh=4.0
    )
    c = Customer(code="CU-A", company_name="Alpha", re_target_percent=50.0)
    db.add_all([f, c])
    db.flush()
    db.add(
        Contract(
            contract_number="EXP-1",
            wind_farm_id=f.id,
            customer_id=c.id,
            start_date=date(2025, 1, 1),
            end_date=date.today() + timedelta(days=60),  # within 6-month horizon
            contracted_percentage=50.0,
            price_per_kwh=5.0,
            priority=1,
            status=ContractStatus.ACTIVE,
        )
    )
    db.commit()


def test_contract_risks_endpoint(client, db):
    _seed_near_expiry(db)
    resp = client.get("/api/v1/analytics/contract-risks?period=2024-01")
    assert resp.status_code == 200
    b = resp.json()
    assert b["counts"]["total"] == len(b["alerts"])
    assert any(a["category"] == "expiry" for a in b["alerts"])
    assert b["horizon_months"] == 6


def test_contract_risks_horizon_override(client, db):
    _seed_near_expiry(db)
    # 1-month horizon excludes the ~60-day expiry
    resp = client.get(
        "/api/v1/analytics/contract-risks?period=2024-01&horizon_months=1"
    )
    assert resp.status_code == 200
    b = resp.json()
    assert b["horizon_months"] == 1
    assert not any(a["category"] == "expiry" for a in b["alerts"])
