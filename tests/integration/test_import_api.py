"""匯入端點：dry_run 參數與補齊的入口。"""

from __future__ import annotations

FARM_CSV = b"code,name,installed_capacity_mw\nWF-A1,A1,100\n"


def _post(client, path, content, **params):
    return client.post(
        path, files={"file": ("in.csv", content, "text/csv")}, params=params
    )


def test_dry_run_reports_without_writing(client):
    resp = _post(client, "/api/v1/wind-farms/import", FARM_CSV, dry_run=True)
    assert resp.status_code == 200
    body = resp.json()
    assert body["imported"] == 1 and body["dry_run"] is True

    assert client.get("/api/v1/wind-farms").json() == []


def test_real_import_writes(client):
    _post(client, "/api/v1/wind-farms/import", FARM_CSV)
    codes = [f["code"] for f in client.get("/api/v1/wind-farms").json()]
    assert codes == ["WF-A1"]


def test_batteries_import_endpoint_exists(client):
    client.post(
        "/api/v1/customers",
        json={
            "code": "CUS-B1",
            "company_name": "B1",
            "annual_consumption_mwh": 1.0,
            "re_target_percent": 10.0,
        },
    )
    csv = b"customer_code,code,name,energy_capacity_mwh,power_mw\nCUS-B1,BAT-1,B,20,5\n"
    resp = _post(client, "/api/v1/batteries/import", csv)
    assert resp.status_code == 200
    assert resp.json()["imported"] == 1


def test_error_groups_collapse_a_systematically_bad_column(client):
    csv = (
        b"code,name,installed_capacity_mw\n"
        b"WF-E1,E1,abc\nWF-E2,E2,def\nWF-E3,E3,ghi\n"
    )
    body = _post(client, "/api/v1/wind-farms/import", csv, dry_run=True).json()

    assert len(body["error_groups"]) == 1
    group = body["error_groups"][0]
    assert group["field"] == "installed_capacity_mw"
    assert group["count"] == 3
    assert group["sample_rows"] == [2, 3, 4]
