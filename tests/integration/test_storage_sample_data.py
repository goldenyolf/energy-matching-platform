"""B5：示範資料帶一具客戶側電池,風光互補之上再加一段。

電池規格取自 2024-01 實測（見 docs/spec-storage-time-shifting.md §4）：
用電廠 2 月缺口約 5,306 MWh、系統單日外溢約 1,547 MWh，充電來源綽綽有餘。
"""

from __future__ import annotations

import pytest

from app.models import Battery, Customer
from app.services import hourly_matching_service as svc


def test_sample_data_has_one_customer_side_battery(seeded_db):
    rows = list(seeded_db.query(Battery))
    assert len(rows) == 1, "示範資料應有 1 具客戶側儲能"
    bat = rows[0]
    assert bat.energy_capacity_mwh == pytest.approx(120.0)
    assert bat.power_mw == pytest.approx(30.0)
    assert bat.round_trip_efficiency_percent == pytest.approx(88.0)


def test_the_battery_belongs_to_the_customer_that_signed_the_solar_ppa(seeded_db):
    bat = seeded_db.query(Battery).one()
    owner = seeded_db.get(Customer, bat.customer_id)
    assert owner.industry == "電源管理"  # 日間型負載,兩輪充電規則都會被走到


def test_storage_lifts_the_demo_portfolio_above_its_no_storage_baseline(seeded_db):
    res = svc.compute_hourly_outcome(seeded_db, "2024-01")
    assert res.no_storage_cfe_percent is not None
    assert res.cfe_percent > res.no_storage_cfe_percent
    assert res.storage_uplift_pt is not None and res.storage_uplift_pt > 0


def test_the_three_segments_are_ordered(seeded_db):
    """只風電 ≤ 風光 ≤ 風光＋儲——每一段各加一件事,不重疊。"""
    res = svc.compute_hourly_outcome(seeded_db, "2024-01")
    assert res.wind_only_cfe_percent is not None
    assert res.no_storage_cfe_percent is not None
    assert res.wind_only_cfe_percent < res.no_storage_cfe_percent < res.cfe_percent


def test_the_battery_owner_alone_has_per_customer_storage_curves(seeded_db):
    """示範資料只有用電廠 2 掛著那具電池——只有它該有非 None 的逐客戶儲能曲線,
    其他客戶（沒有電池）兩者皆為 None。"""
    bat = seeded_db.query(Battery).one()
    res = svc.compute_hourly_outcome(seeded_db, "2024-01")

    owner = next(x for x in res.customers if x.customer_id == bat.customer_id)
    assert owner.discharged_by_hour is not None and len(owner.discharged_by_hour) == 24
    assert owner.soc_by_hour is not None and len(owner.soc_by_hour) == 24

    others = [c for c in res.customers if c.customer_id != bat.customer_id]
    assert others, "示範投組應該有其他客戶作對照"
    assert all(c.discharged_by_hour is None for c in others)
    assert all(c.soc_by_hour is None for c in others)


def test_the_battery_owner_s_two_uplifts_decompose_the_total(seeded_db):
    """迴歸測試：用電廠 2（風＋光＋儲能都簽了）的 uplift_pt 曾誤把儲能的增益也算
    進太陽能頭上。正確算法下,兩段各自的貢獻加總要等於總增益,不重疊、不遺漏。"""
    bat = seeded_db.query(Battery).one()
    owner = seeded_db.get(Customer, bat.customer_id)

    res = svc.compute_hourly_outcome(seeded_db, "2024-01")
    c = next(x for x in res.customers if x.customer_id == owner.id)

    assert c.wind_only_cfe_percent is not None
    assert c.no_storage_cfe_percent is not None
    assert c.uplift_pt == pytest.approx(
        round(c.no_storage_cfe_percent - c.wind_only_cfe_percent, 2)
    )
    assert c.storage_uplift_pt == pytest.approx(
        round(c.cfe_percent - c.no_storage_cfe_percent, 2)
    )
    assert c.uplift_pt + c.storage_uplift_pt == pytest.approx(
        round(c.cfe_percent - c.wind_only_cfe_percent, 2)
    )
