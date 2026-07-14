"""Integration tests for the REST API."""

from __future__ import annotations

V1 = "/api/v1"


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_wind_farm_crud(client):
    payload = {
        "code": "WF-TEST",
        "name": "Test Farm",
        "installed_capacity_mw": 100,
        "status": "operational",
    }
    created = client.post(f"{V1}/wind-farms", json=payload)
    assert created.status_code == 201
    farm_id = created.json()["id"]

    assert client.get(f"{V1}/wind-farms/{farm_id}").status_code == 200
    assert len(client.get(f"{V1}/wind-farms").json()) == 1

    # duplicate code -> 409
    assert client.post(f"{V1}/wind-farms", json=payload).status_code == 409
    # missing -> 404
    assert client.get(f"{V1}/wind-farms/9999").status_code == 404


def test_wind_farm_validation_error(client):
    bad = {"code": "X", "name": "Y", "installed_capacity_mw": -5}
    assert client.post(f"{V1}/wind-farms", json=bad).status_code == 422


def test_contract_requires_existing_fks(client):
    payload = {
        "contract_number": "PPA-X",
        "wind_farm_id": 123,
        "customer_id": 456,
        "start_date": "2024-01-01",
        "end_date": "2025-01-01",
        "contracted_percentage": 50,
        "priority": 1,
        "status": "active",
    }
    assert client.post(f"{V1}/contracts", json=payload).status_code == 422


def test_generation_csv_import(client):
    client.post(
        f"{V1}/wind-farms",
        json={"code": "WF-IMP", "name": "Imp", "installed_capacity_mw": 50},
    )
    csv = (
        "wind_farm_code,period_start,period_end,generated_energy_mwh,data_source\n"
        "WF-IMP,2024-01-01,2024-01-31,1000,mock\n"
        "WF-IMP,2024-02-01,2024-02-29,900,mock\n"
    )
    resp = client.post(
        f"{V1}/generation/import",
        files={"file": ("generation.csv", csv, "text/csv")},
    )
    assert resp.status_code == 200
    assert resp.json()["imported"] == 2
    assert len(client.get(f"{V1}/generation").json()) == 2


def test_full_matching_flow_via_api(client):
    # 1 farm, 1 customer, 1 contract, 1 month of data
    wf = client.post(
        f"{V1}/wind-farms",
        json={"code": "WF-A", "name": "A", "installed_capacity_mw": 100},
    ).json()
    cu = client.post(
        f"{V1}/customers",
        json={
            "code": "C-A",
            "company_name": "Co A",
            "annual_consumption_mwh": 1200,
            "re_target_percent": 100,
            "target_year": 2030,
        },
    ).json()
    client.post(
        f"{V1}/contracts",
        json={
            "contract_number": "PPA-A",
            "wind_farm_id": wf["id"],
            "customer_id": cu["id"],
            "start_date": "2024-01-01",
            "end_date": "2025-01-01",
            "contracted_percentage": 100,
            "priority": 1,
            "status": "active",
        },
    )
    client.post(
        f"{V1}/generation",
        json={
            "wind_farm_id": wf["id"],
            "period_start": "2024-01-01",
            "period_end": "2024-01-31",
            "generated_energy_mwh": 80,
        },
    )
    client.post(
        f"{V1}/consumption",
        json={
            "customer_id": cu["id"],
            "period_start": "2024-01-01",
            "period_end": "2024-01-31",
            "consumed_energy_mwh": 100,
        },
    )

    run = client.post(f"{V1}/matching/runs", json={"period": "2024-01"})
    assert run.status_code == 201
    body = run.json()
    assert body["status"] == "completed"
    # farm supplies 80, customer wants 100 -> allocation capped at 80
    assert body["result_summary"]["total_allocated_mwh"] == 80.0

    runs = client.get(f"{V1}/matching/runs")
    assert len(runs.json()) == 1

    detail = client.get(f"{V1}/matching/runs/{body['id']}")
    assert detail.status_code == 200
    assert len(detail.json()["results"]) >= 1

    analytics = client.get(
        f"{V1}/analytics/customers", params={"period": "2024-01"}
    ).json()
    assert analytics[0]["achieved_re_percent"] == 80.0

    summary = client.get(f"{V1}/analytics/summary", params={"period": "2024-01"}).json()
    assert summary["total_generation_mwh"] == 80.0


def test_matching_run_invalid_period(client):
    assert (
        client.post(f"{V1}/matching/runs", json={"period": "2024-13"}).status_code
        == 422
    )
    assert client.post(f"{V1}/matching/runs", json={"period": "bad"}).status_code == 422


def test_matching_run_not_found(client):
    assert client.get(f"{V1}/matching/runs/999").status_code == 404
