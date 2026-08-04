"""範本與欄位表端點。範本必須是「下載下來原封不動就能匯回去」的合法輸入。"""

from __future__ import annotations

import csv
import io

from app.ingestion.schema import SPECS


def test_schema_endpoint_lists_every_entity(client):
    resp = client.get("/api/v1/import/schema")
    assert resp.status_code == 200
    entities = {e["entity"] for e in resp.json()["entities"]}
    assert entities == set(SPECS)


def test_schema_endpoint_exposes_labels_and_notes(client):
    body = client.get("/api/v1/import/schema").json()
    contract = next(e for e in body["entities"] if e["entity"] == "contract")
    shares = next(c for c in contract["columns"] if c["name"] == "monthly_shares")
    assert shares["label"] == "月別配比"
    assert shares["note"] and "分號" in shares["note"]


def test_schema_endpoint_needs_no_write_token(client, monkeypatch):
    """欄位定義不含任何資料，不該被寫入閘擋住。"""
    from app.core.config import settings

    monkeypatch.setattr(settings, "admin_write_token", "secret")
    assert client.get("/api/v1/import/schema").status_code == 200


def test_template_has_bom_so_excel_reads_chinese(client):
    resp = client.get("/api/v1/import/template/farm")
    assert resp.status_code == 200
    assert resp.content.startswith(b"\xef\xbb\xbf"), "缺 BOM，Excel 開中文會亂碼"
    assert "attachment" in resp.headers["content-disposition"]
    assert "farm_template.csv" in resp.headers["content-disposition"]


def test_template_header_matches_the_spec(client):
    resp = client.get("/api/v1/import/template/customer")
    rows = list(csv.reader(io.StringIO(resp.content.decode("utf-8-sig"))))
    assert tuple(rows[0]) == SPECS["customer"].column_names()
    assert len(rows) == 2, "範本應為標題列＋一列示範值"


def test_unknown_entity_is_404(client):
    assert client.get("/api/v1/import/template/nope").status_code == 404


def test_downloaded_template_imports_straight_back(client):
    """範本永遠是合法輸入——全部七種實體都要驗，不是只驗沒有外鍵的兩類。

    有外鍵的五類（meter／battery／contract／generation／consumption）範本的
    範例值都指向 ``WF-001``／``CUS-001``（FARM.code／CUSTOMER.code 各自的
    ``example``），所以先把 farm／customer 的範本匯進去，其餘五類的外鍵範例
    才能真的解析成功，而不是各自獨立測，那樣會漏掉「範例代碼有沒有串得起來」
    這件事本身。
    """
    order = [
        ("farm", "wind-farms"),
        ("customer", "customers"),
        ("meter", "meters"),
        ("battery", "batteries"),
        ("contract", "contracts"),
        ("generation", "generation"),
        ("consumption", "consumption"),
    ]
    assert {entity for entity, _ in order} == set(SPECS), "漏掉了某個實體"
    for entity, path in order:
        content = client.get(f"/api/v1/import/template/{entity}").content
        resp = client.post(
            f"/api/v1/{path}/import",
            files={"file": (f"{entity}.csv", content, "text/csv")},
        )
        assert resp.status_code == 200, entity
        body = resp.json()
        assert body["imported"] == 1, f"{entity} 範本匯不回去: {body}"
        assert body["errors"] == [], f"{entity} 範本自帶錯誤: {body['errors']}"
