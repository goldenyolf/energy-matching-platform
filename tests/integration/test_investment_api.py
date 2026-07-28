from __future__ import annotations

from app.ingestion import csv_importer


def _seed(db):
    csv_importer.import_wind_farms(
        db,
        [
            {
                "code": "WF-A",
                "name": "海能",
                "installed_capacity_mw": "100",
                "status": "operational",
                "feed_in_price_per_kwh": "4.0",
            }
        ],
    )
    csv_importer.import_generation(
        db,
        [
            {
                "wind_farm_code": "WF-A",
                "period_start": "2024-01-01",
                "period_end": "2024-01-31",
                "generated_energy_mwh": "400000",
                "data_source": "t",
            }
        ],
    )


def test_investment_endpoint_default_config(client, db):
    _seed(db)
    resp = client.get("/api/v1/analytics/investment")
    assert resp.status_code == 200
    body = resp.json()
    assert body["capex_per_mw"] == 80_000_000.0
    assert body["om_rate_percent"] == 2.0
    farm = body["farms"][0]
    assert farm["capex"] == 100.0 * 80_000_000.0
    assert farm["annual_revenue"] == 400_000.0 * 1000 * 4.0
    assert body["total"]["annual_net"] == farm["annual_net"]


def test_investment_scenario_p50_p90_uses_capacity_factor(client, db):
    csv_importer.import_wind_farms(
        db,
        [
            {
                "code": "WF-CF",
                "name": "離岸",
                "installed_capacity_mw": "100",
                "status": "operational",
                "feed_in_price_per_kwh": "4.0",
                "farm_type": "offshore",
                "capacity_factor_percent": "45",
                "p90_capacity_factor_percent": "40",
            }
        ],
    )
    # actual scenario: no generation rows → 0
    assert (
        client.get("/api/v1/analytics/investment").json()["farms"][0][
            "annual_generation_mwh"
        ]
        == 0.0
    )
    # p50: 100 MW × 8760 h × 45% = 394,200 MWh
    p50 = client.get("/api/v1/analytics/investment?scenario=p50").json()
    assert p50["scenario"] == "p50"
    assert p50["farms"][0]["annual_generation_mwh"] == 100 * 8760 * 0.45
    assert p50["farms"][0]["capacity_factor_percent"] == 45.0
    # p90 is the conservative (lower) yield
    p90 = client.get("/api/v1/analytics/investment?scenario=p90").json()
    assert p90["farms"][0]["annual_generation_mwh"] == 100 * 8760 * 0.40
    assert p90["farms"][0]["annual_net"] < p50["farms"][0]["annual_net"]


def test_investment_endpoint_override(client, db):
    _seed(db)
    resp = client.get(
        "/api/v1/analytics/investment?capex_per_mw=50000000&om_rate_percent=3"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["capex_per_mw"] == 50_000_000.0
    assert body["om_rate_percent"] == 3.0
    assert body["farms"][0]["capex"] == 100.0 * 50_000_000.0
