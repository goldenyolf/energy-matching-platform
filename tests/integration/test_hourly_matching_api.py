"""API test: GET /api/v1/matching/hourly against the seeded demo dataset."""

from __future__ import annotations


def test_hourly_endpoint_returns_cfe_below_paper(client, seeded_db):
    resp = client.get("/api/v1/matching/hourly", params={"period": "2024-01"})
    assert resp.status_code == 200
    body = resp.json()

    assert body["modeled"] is True
    assert body["hours"] == 24
    assert len(body["matched_by_hour"]) == 24
    # True 24/7 CFE never exceeds the paper monthly-netting figure.
    assert body["cfe_percent"] <= body["paper_re_percent"] + 1e-6
    assert body["customers"], "expected per-customer CFE rows"
    for c in body["customers"]:
        assert 0.0 <= c["cfe_percent"] <= 100.0


def test_hourly_endpoint_customer_filter(client, seeded_db):
    full = client.get("/api/v1/matching/hourly", params={"period": "2024-01"}).json()
    target = full["customers"][0]["customer_id"]
    one = client.get(
        "/api/v1/matching/hourly",
        params={"period": "2024-01", "customer_id": target},
    ).json()
    assert [c["customer_id"] for c in one["customers"]] == [target]
