"""合約詳情端點。除了 happy path,也對示範資料釘住兩個具體事實——
它們是這一頁存在的理由,壞掉時要在 CI 就看到。"""

from __future__ import annotations


def _detail(client, number: str, year: int = 2024):
    contracts = client.get("/api/v1/contracts?limit=1000").json()
    cid = next(c["id"] for c in contracts if c["contract_number"] == number)
    resp = client.get(
        f"/api/v1/analytics/contract-detail?contract_id={cid}&year={year}"
    )
    assert resp.status_code == 200
    return resp.json()


def test_contract_detail_endpoint(client, seeded_db):
    d = _detail(client, "PPA-2022-005")
    assert len(d["months"]) == 12
    assert d["has_period_data"] is True
    assert d["has_price"] is True
    # 釘住實際分佈,不是「加起來有 12 個月」——後者跟上面的 len(months) == 12
    # 是同一件事,永遠不會紅。005 是拿滿上限的合約,12 個月全被合約上限卡住。
    assert d["totals"]["binding_counts"] == {"contract_cap": 12}


def test_unknown_contract_is_404(client, seeded_db):
    resp = client.get("/api/v1/analytics/contract-detail?contract_id=9999&year=2024")
    assert resp.status_code == 404


def test_year_without_data_still_returns_the_terms(client, seeded_db):
    d = _detail(client, "PPA-2022-005", year=2030)
    assert d["has_period_data"] is False
    assert len(d["months"]) == 12
    assert d["contracted_energy_mwh"] == 15000.0


def test_sample_contract_004_is_supply_bound_all_year(client, seeded_db):
    """FORMOSA2 上排在優先序 3,前面的合約把電吃光——這是頁面上最有話講的一種。"""
    d = _detail(client, "PPA-2024-004")
    assert all(m["binding_primary"] == "farm_supply" for m in d["months"])
    assert d["higher_priority_sibling_count"] > 0
    assert all(m["headroom"] is False for m in d["months"])


def test_sample_contract_005_never_triggers_take_or_pay(client, seeded_db):
    """保證量 80%,但每月都拿滿上限 → 全年零差額。頁面要照實寫「未觸發」。"""
    d = _detail(client, "PPA-2022-005")
    assert d["min_offtake_percent"] == 80.0
    assert d["totals"]["shortfall_mwh"] == 0.0
    assert d["totals"]["shortfall_months"] == 0


def test_pending_contract_is_out_of_force_not_zero(client, seeded_db):
    d = _detail(client, "PPA-2025-008")
    assert all(m["in_force"] is False for m in d["months"])
    assert all(m["binding_primary"] == "not_in_force" for m in d["months"])
    assert d["monthly_share_fractions"] is not None  # 條款照樣要看得到
