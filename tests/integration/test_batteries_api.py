"""Battery CRUD endpoints (A8)."""

from __future__ import annotations

import pytest

from app.models import Customer


@pytest.fixture()
def customer_id(client, session_factory):
    db = session_factory()
    c = Customer(code="K1", company_name="用電廠一", industry="電源管理")
    db.add(c)
    db.commit()
    cid = c.id
    db.close()
    return cid


def _payload(customer_id: int) -> dict:
    return {
        "code": "BAT-DEMO",
        "customer_id": customer_id,
        "name": "示範儲能",
        "energy_capacity_mwh": 120.0,
        "power_mw": 30.0,
    }


def test_create_then_read_a_battery(client, customer_id):
    created = client.post("/api/v1/batteries", json=_payload(customer_id))
    assert created.status_code == 201
    body = created.json()
    assert body["code"] == "BAT-DEMO"
    assert body["round_trip_efficiency_percent"] == 88.0

    fetched = client.get(f"/api/v1/batteries/{body['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["energy_capacity_mwh"] == 120.0


def test_duplicate_code_is_rejected(client, customer_id):
    client.post("/api/v1/batteries", json=_payload(customer_id))
    again = client.post("/api/v1/batteries", json=_payload(customer_id))
    assert again.status_code == 409


def test_list_can_filter_by_customer(client, customer_id):
    client.post("/api/v1/batteries", json=_payload(customer_id))
    rows = client.get("/api/v1/batteries", params={"customer_id": customer_id}).json()
    assert [r["code"] for r in rows] == ["BAT-DEMO"]
    assert client.get("/api/v1/batteries", params={"customer_id": 99999}).json() == []


def test_update_and_delete(client, customer_id):
    bid = client.post("/api/v1/batteries", json=_payload(customer_id)).json()["id"]

    updated = client.put(f"/api/v1/batteries/{bid}", json={"power_mw": 45.0})
    assert updated.status_code == 200
    assert updated.json()["power_mw"] == 45.0

    assert client.delete(f"/api/v1/batteries/{bid}").status_code == 204
    assert client.get(f"/api/v1/batteries/{bid}").status_code == 404
