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
