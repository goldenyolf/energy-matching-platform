from __future__ import annotations

from app.ingestion import csv_importer


def _seed(db):
    csv_importer.import_wind_farms(
        db,
        [
            {
                "code": "WF-A",
                "name": "A",
                "installed_capacity_mw": "10",
                "status": "operational",
                "feed_in_price_per_kwh": "4.0",
            }
        ],
    )
    csv_importer.import_customers(
        db,
        [
            {
                "code": "CU-A",
                "company_name": "Alpha",
                "annual_consumption_mwh": "2400",
                "re_target_percent": "50",
            }
        ],
    )
    csv_importer.import_contracts(
        db,
        [
            {
                "contract_number": "PPA-A",
                "wind_farm_code": "WF-A",
                "customer_code": "CU-A",
                "start_date": "2025-01-01",
                "end_date": "2030-12-31",
                "contracted_percentage": "100",
                "price_per_kwh": "5.0",
                "priority": "1",
                "status": "active",
            }
        ],
    )
    csv_importer.import_generation(
        db,
        [
            {
                "wind_farm_code": "WF-A",
                "period_start": "2025-01-01",
                "period_end": "2025-01-31",
                "generated_energy_mwh": "100",
                "data_source": "t",
            }
        ],
    )
    csv_importer.import_consumption(
        db,
        [
            {
                "customer_code": "CU-A",
                "period_start": "2025-01-01",
                "period_end": "2025-01-31",
                "consumed_energy_mwh": "200",
                "data_source": "t",
            }
        ],
    )
    from app.models import Customer

    return db.query(Customer).filter_by(code="CU-A").one().id


def test_evaluation_endpoint_returns_dual_report(client, db):
    cid = _seed(db)
    resp = client.get(
        f"/api/v1/analytics/evaluation?customer_id={cid}&start=2025-01&end=2025-01"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["seller"]["gross_profit"] == 100000.0
    assert body["buyer"]["re_percent"] == 50.0


def test_evaluation_endpoint_unknown_customer_404(client):
    resp = client.get("/api/v1/analytics/evaluation?customer_id=999999")
    assert resp.status_code == 404
