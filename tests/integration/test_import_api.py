"""匯入端點：dry_run 參數與補齊的入口。"""

from __future__ import annotations

import pytest

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


_FARM_SEED_CSV = b"code,name,installed_capacity_mw\nWF-DR1,DR1,10\n"
_CUSTOMER_SEED_CSV = b"code,company_name\nCUS-DR1,DR1\n"

# entity path → (seed imports needed for its foreign keys, one-row CSV to dry-run)
_DRY_RUN_ENTITIES: dict[str, tuple[list[tuple[str, bytes]], bytes]] = {
    "wind-farms": ([], b"code,name,installed_capacity_mw\nWF-DR2,DR2,100\n"),
    "customers": ([], b"code,company_name\nCUS-DR2,DR2\n"),
    "meters": (
        [("customers", _CUSTOMER_SEED_CSV)],
        b"customer_code,code,name\nCUS-DR1,MTR-DR1,M1\n",
    ),
    "batteries": (
        [("customers", _CUSTOMER_SEED_CSV)],
        b"customer_code,code,name,energy_capacity_mwh,power_mw\n"
        b"CUS-DR1,BAT-DR1,B1,20,5\n",
    ),
    "contracts": (
        [("wind-farms", _FARM_SEED_CSV), ("customers", _CUSTOMER_SEED_CSV)],
        b"contract_number,wind_farm_code,customer_code,start_date,end_date,"
        b"contracted_percentage\nPPA-DR1,WF-DR1,CUS-DR1,2026-01-01,2026-12-31,50\n",
    ),
    "generation": (
        [("wind-farms", _FARM_SEED_CSV)],
        b"wind_farm_code,period_start,period_end,generated_energy_mwh\n"
        b"WF-DR1,2026-01-01,2026-01-31,1000\n",
    ),
    "consumption": (
        [("customers", _CUSTOMER_SEED_CSV)],
        b"customer_code,period_start,period_end,consumed_energy_mwh\n"
        b"CUS-DR1,2026-01-01,2026-01-31,900\n",
    ),
}


@pytest.mark.parametrize("path", sorted(_DRY_RUN_ENTITIES))
def test_dry_run_reports_without_writing_for_every_entity(client, path):
    """§4.5 承諾 dry-run 對全部七種實體都不落地——但只有 wind-farms 被測到的
    話，複製貼上七個 ``/import`` 端點時漏掉某一個的 ``dry_run=dry_run`` 會沒有
    測試抓到。每個實體都跑一次同樣的斷言：dry-run 回報有 1 筆，但清單仍是空的。
    """
    seeds, csv = _DRY_RUN_ENTITIES[path]
    for seed_path, seed_csv in seeds:
        seed_resp = _post(client, f"/api/v1/{seed_path}/import", seed_csv)
        assert seed_resp.status_code == 200, (seed_path, seed_resp.text)

    resp = _post(client, f"/api/v1/{path}/import", csv, dry_run=True)
    assert resp.status_code == 200, (path, resp.text)
    body = resp.json()
    assert body["imported"] == 1 and body["dry_run"] is True, (path, body)

    assert client.get(f"/api/v1/{path}").json() == [], path


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
