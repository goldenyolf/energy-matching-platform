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


def test_customer_extended_fields_roundtrip(client):
    resp = client.post(
        "/api/v1/customers",
        json={
            "code": "CUST-EXT",
            "company_name": "Ext Co",
            "re_target_percent": 50.0,
            "contracted_capacity_kw": 8000.0,
            "transfer_price_per_kwh": 4.6,
            "tariff_type": "three_stage",
            "peak_price_per_kwh": 6.2,
            "half_peak_price_per_kwh": 4.5,
            "off_peak_price_per_kwh": 2.3,
        },
    )
    assert resp.status_code == 201
    b = resp.json()
    assert b["contracted_capacity_kw"] == 8000.0
    assert b["tariff_type"] == "three_stage"
    assert b["peak_price_per_kwh"] == 6.2
    up = client.put(
        f"/api/v1/customers/{b['id']}",
        json={"contracted_capacity_kw": 9000.0, "off_peak_price_per_kwh": 2.1},
    )
    assert up.status_code == 200
    assert up.json()["contracted_capacity_kw"] == 9000.0
    assert up.json()["off_peak_price_per_kwh"] == 2.1


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
