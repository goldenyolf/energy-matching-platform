"""API 端點測試 (FastAPI TestClient)。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_get_dataset():
    resp = client.get("/dataset")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["wind_farms"]) > 0
    assert len(body["companies"]) > 0


def test_match_sample():
    resp = client.get("/match")
    assert resp.status_code == 200
    body = resp.json()
    assert "summary" in body
    assert body["summary"]["company_count"] == len(body["company_results"])
    # 分配量不可超過總發電量
    assert (
        body["summary"]["total_allocated_mwh"]
        <= body["summary"]["total_generation_mwh"] + 1e-3
    )


def test_match_custom_dataset():
    payload = {
        "wind_farms": [
            {
                "id": "wf1",
                "name": "Test",
                "location": "海上",
                "capacity_mw": 100,
                "annual_generation_mwh": 1000,
            }
        ],
        "companies": [
            {
                "id": "co1",
                "name": "C",
                "industry": "t",
                "annual_consumption_mwh": 1000,
                "re_target_ratio": 1.0,
            }
        ],
        "contracts": [
            {
                "id": "ct1",
                "company_id": "co1",
                "wind_farm_id": "wf1",
                "allocation_type": "ratio",
                "value": 0.5,
                "price_per_kwh": 4.5,
                "start_year": 2025,
            }
        ],
    }
    resp = client.post("/match", json=payload)
    assert resp.status_code == 200
    assert resp.json()["allocations"][0]["allocated_mwh"] == 500.0


def test_match_custom_invalid_reference_returns_422():
    payload = {
        "wind_farms": [
            {
                "id": "wf1",
                "name": "Test",
                "location": "海上",
                "capacity_mw": 100,
                "annual_generation_mwh": 1000,
            }
        ],
        "companies": [],
        "contracts": [
            {
                "id": "ct1",
                "company_id": "ghost",
                "wind_farm_id": "wf1",
                "allocation_type": "ratio",
                "value": 0.5,
                "price_per_kwh": 4.5,
                "start_year": 2025,
            }
        ],
    }
    resp = client.post("/match", json=payload)
    assert resp.status_code == 422


def test_company_analysis_found():
    resp = client.get("/companies/co-tsmc")
    assert resp.status_code == 200
    assert resp.json()["company_id"] == "co-tsmc"


def test_company_analysis_not_found():
    resp = client.get("/companies/does-not-exist")
    assert resp.status_code == 404
