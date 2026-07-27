"""CRUD (update / delete) + write-gate for wind-farms and customers."""

from __future__ import annotations

from datetime import date

from app.core.config import settings
from app.models import ConsumptionData, GenerationData


def _make_farm(client, code="WF-NEW"):
    return client.post(
        "/api/v1/wind-farms",
        json={"code": code, "name": "New Farm", "installed_capacity_mw": 50.0},
    )


def _make_customer(client, code="CUST-NEW"):
    return client.post(
        "/api/v1/customers",
        json={"code": code, "company_name": "New Co", "re_target_percent": 40.0},
    )


def test_update_wind_farm(client):
    fid = _make_farm(client).json()["id"]
    resp = client.put(
        f"/api/v1/wind-farms/{fid}",
        json={"name": "Renamed", "feed_in_price_per_kwh": 4.7},
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Renamed"
    assert resp.json()["feed_in_price_per_kwh"] == 4.7


def test_delete_wind_farm_without_dependents(client):
    fid = _make_farm(client).json()["id"]
    assert client.delete(f"/api/v1/wind-farms/{fid}").status_code == 204
    assert client.get(f"/api/v1/wind-farms/{fid}").status_code == 404


def test_delete_wind_farm_blocked_by_generation(client, db):
    fid = _make_farm(client).json()["id"]
    db.add(
        GenerationData(
            wind_farm_id=fid,
            period_start=date(2024, 1, 1),
            period_end=date(2024, 1, 31),
            generated_energy_mwh=10.0,
        )
    )
    db.commit()
    resp = client.delete(f"/api/v1/wind-farms/{fid}")
    assert resp.status_code == 409
    assert "發電" in resp.json()["detail"]


def test_update_customer(client):
    cid = _make_customer(client).json()["id"]
    resp = client.put(
        f"/api/v1/customers/{cid}",
        json={"company_name": "Renamed Co", "re_target_percent": 90.0},
    )
    assert resp.status_code == 200
    assert resp.json()["company_name"] == "Renamed Co"
    assert resp.json()["re_target_percent"] == 90.0


def test_customer_company_fields_roundtrip(client):
    resp = client.post(
        "/api/v1/customers",
        json={
            "code": "CUST-EXT",
            "company_name": "世通國際",
            "re_target_percent": 50.0,
            "tax_id": "22153346",
            "address": "桃園市龍潭區中原路二段一號",
            "contact_name": "王小明",
            "transfer_price_per_kwh": 4.6,
        },
    )
    assert resp.status_code == 201
    b = resp.json()
    assert b["tax_id"] == "22153346"
    assert b["address"] == "桃園市龍潭區中原路二段一號"
    assert b["transfer_price_per_kwh"] == 4.6
    up = client.put(
        f"/api/v1/customers/{b['id']}",
        json={"contact_email": "a@b.com", "phone": "03-1234567"},
    )
    assert up.status_code == 200
    assert up.json()["contact_email"] == "a@b.com"
    assert up.json()["phone"] == "03-1234567"


def _make_meter_customer(client):
    return _make_customer(client, code="CUST-MTR").json()["id"]


def test_meter_crud_roundtrip(client):
    cid = _make_meter_customer(client)
    created = client.post(
        "/api/v1/meters",
        json={
            "code": "04-95-4331-15-3",
            "customer_id": cid,
            "name": "龍潭廠",
            "contracted_capacity_kw": 260.0,
            "tariff_type": "hv_three_stage",
            "peak_kwh": 67497.0,
            "half_peak_kwh": 1168825.0,
            "saturday_half_peak_kwh": 43115.0,
            "off_peak_kwh": 626909.0,
            "total_kwh": 1906346.0,
            "data_period": "2023-01~2023-12",
        },
    )
    assert created.status_code == 201
    m = created.json()
    assert m["saturday_half_peak_kwh"] == 43115.0
    assert m["tariff_type"] == "hv_three_stage"
    up = client.put(f"/api/v1/meters/{m['id']}", json={"contracted_capacity_kw": 300.0})
    assert up.status_code == 200
    assert up.json()["contracted_capacity_kw"] == 300.0
    # list filtered by customer
    lst = client.get("/api/v1/meters", params={"customer_id": cid}).json()
    assert any(x["id"] == m["id"] for x in lst)
    # delete (no consumption) → 204
    assert client.delete(f"/api/v1/meters/{m['id']}").status_code == 204


def test_meter_delete_blocked_by_consumption(client, db):
    from app.models import ConsumptionData, Meter

    cid = _make_customer(client, code="CUST-MTR2").json()["id"]
    meter = Meter(code="M-BLK", customer_id=cid, name="M")
    db.add(meter)
    db.flush()
    db.add(
        ConsumptionData(
            customer_id=cid,
            meter_id=meter.id,
            period_start=date(2024, 1, 1),
            period_end=date(2024, 1, 31),
            consumed_energy_mwh=5.0,
        )
    )
    db.commit()
    resp = client.delete(f"/api/v1/meters/{meter.id}")
    assert resp.status_code == 409
    assert "用電" in resp.json()["detail"]


def test_delete_customer_blocked_by_consumption(client, db):
    cid = _make_customer(client).json()["id"]
    db.add(
        ConsumptionData(
            customer_id=cid,
            period_start=date(2024, 1, 1),
            period_end=date(2024, 1, 31),
            consumed_energy_mwh=10.0,
        )
    )
    db.commit()
    resp = client.delete(f"/api/v1/customers/{cid}")
    assert resp.status_code == 409
    assert "用電" in resp.json()["detail"]


def test_write_gate_requires_token(client, monkeypatch):
    monkeypatch.setattr(settings, "admin_write_token", "secret")
    # no token → blocked
    assert _make_farm(client, code="WF-GATED").status_code == 403
    # correct token → allowed
    ok = client.post(
        "/api/v1/wind-farms",
        json={"code": "WF-GATED", "name": "G", "installed_capacity_mw": 5.0},
        headers={"X-Admin-Token": "secret"},
    )
    assert ok.status_code == 201
