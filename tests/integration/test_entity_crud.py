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


def test_customer_basic_fields_roundtrip(client):
    resp = client.post(
        "/api/v1/customers",
        json={
            "code": "CUST-EXT",
            "company_name": "世通國際",
            "industry": "半導體",
            "annual_consumption_mwh": 1906.0,
            "re_target_percent": 50.0,
            "target_year": 2030,
        },
    )
    assert resp.status_code == 201
    b = resp.json()
    assert b["industry"] == "半導體"
    assert b["annual_consumption_mwh"] == 1906.0
    up = client.put(f"/api/v1/customers/{b['id']}", json={"target_year": 2035})
    assert up.status_code == 200
    assert up.json()["target_year"] == 2035


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


def _make_contract(client, number="PPA-NEW"):
    fid = _make_farm(client, code="WF-CT").json()["id"]
    cid = _make_customer(client, code="CUST-CT").json()["id"]
    return client.post(
        "/api/v1/contracts",
        json={
            "contract_number": number,
            "wind_farm_id": fid,
            "customer_id": cid,
            "start_date": "2024-01-01",
            "end_date": "2033-12-31",
            "contracted_percentage": 60.0,
            "price_per_kwh": 4.8,
        },
    )


def test_update_contract(client):
    resp = _make_contract(client)
    assert resp.status_code == 201
    ct = resp.json()
    up = client.put(
        f"/api/v1/contracts/{ct['id']}",
        json={"price_per_kwh": 5.1, "status": "terminated"},
    )
    assert up.status_code == 200
    assert up.json()["price_per_kwh"] == 5.1
    assert up.json()["status"] == "terminated"


def test_delete_contract_without_dependents(client):
    cid = _make_contract(client).json()["id"]
    assert client.delete(f"/api/v1/contracts/{cid}").status_code == 204
    assert client.get(f"/api/v1/contracts/{cid}").status_code == 404


def test_delete_contract_blocked_by_matching_result(client, db):
    from app.models import MatchingResult, MatchingRun

    ct = _make_contract(client).json()
    run = MatchingRun(period="2024-01")
    db.add(run)
    db.flush()
    db.add(
        MatchingResult(
            matching_run_id=run.id,
            wind_farm_id=ct["wind_farm_id"],
            customer_id=ct["customer_id"],
            contract_id=ct["id"],
            period="2024-01",
            allocated_energy_mwh=100.0,
            customer_consumption_mwh=200.0,
            achieved_re_percent=50.0,
            allocation_reason="test",
        )
    )
    db.commit()
    resp = client.delete(f"/api/v1/contracts/{ct['id']}")
    assert resp.status_code == 409
    assert "媒合結果" in resp.json()["detail"]


def test_contract_write_gate(client, monkeypatch):
    monkeypatch.setattr(settings, "admin_write_token", "secret")
    # a create without token is blocked (403) before touching the DB
    blocked = client.post(
        "/api/v1/contracts",
        json={
            "contract_number": "PPA-GATED",
            "wind_farm_id": 1,
            "customer_id": 1,
            "start_date": "2024-01-01",
            "end_date": "2030-01-01",
            "contracted_percentage": 50.0,
        },
    )
    assert blocked.status_code == 403


def test_import_wind_farms_csv(client):
    csv = (
        "code,name,installed_capacity_mw\n"
        "WF-CSV1,匯入風場一,60\n"
        "WF-CSV2,匯入風場二,80\n"
    )
    r = client.post(
        "/api/v1/wind-farms/import", files={"file": ("f.csv", csv, "text/csv")}
    )
    assert r.status_code == 200
    assert r.json()["imported"] == 2
    codes = [f["code"] for f in client.get("/api/v1/wind-farms").json()]
    assert "WF-CSV1" in codes and "WF-CSV2" in codes


def test_entity_import_endpoints_require_token(client, monkeypatch):
    monkeypatch.setattr(settings, "admin_write_token", "secret")
    csv = "code,name,installed_capacity_mw\nWF-G,g,1\n"
    for path in ("wind-farms", "customers", "contracts", "meters"):
        r = client.post(
            f"/api/v1/{path}/import", files={"file": ("f.csv", csv, "text/csv")}
        )
        assert r.status_code == 403, path


def test_import_endpoints_require_token(client, monkeypatch):
    monkeypatch.setattr(settings, "admin_write_token", "secret")
    gcsv = (
        "wind_farm_code,period_start,period_end,generated_energy_mwh,data_source\n"
        "WF-X,2024-01-01,2024-01-31,1,mock\n"
    )
    ccsv = (
        "customer_code,period_start,period_end,consumed_energy_mwh,data_source\n"
        "C-X,2024-01-01,2024-01-31,1,mock\n"
    )
    g = client.post(
        "/api/v1/generation/import", files={"file": ("g.csv", gcsv, "text/csv")}
    )
    assert g.status_code == 403
    c = client.post(
        "/api/v1/consumption/import", files={"file": ("c.csv", ccsv, "text/csv")}
    )
    assert c.status_code == 403
    # ...and the correct token lets it through
    ok = client.post(
        "/api/v1/generation/import",
        files={"file": ("g.csv", gcsv, "text/csv")},
        headers={"X-Admin-Token": "secret"},
    )
    assert ok.status_code == 200


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
