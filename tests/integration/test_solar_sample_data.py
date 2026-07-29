"""A7: the bundled demo dataset carries a solar site with a daytime contract.

Solar lives in the same table as wind (``farm_type="solar"``), so the whole
existing pipeline — contracts, generation, hourly matching — picks it up with no
engine change; 風光互補 then shows up on its own in the 2024-01 hourly view.
"""

from __future__ import annotations

import pytest

from app.models import Contract, Customer, GenerationData, WindFarm
from app.services import hourly_matching_service as svc

DAYTIME_INDUSTRIES = {"電源管理", "面板", "電子"}


def _solar_farm(db) -> WindFarm:
    farms = list(db.query(WindFarm).filter(WindFarm.farm_type == "solar"))
    assert len(farms) == 1, "示範資料應有 1 座地面型光電"
    return farms[0]


def test_sample_data_has_one_ground_mount_solar_site(seeded_db):
    farm = _solar_farm(seeded_db)
    assert farm.installed_capacity_mw > 0
    # 太陽能 CF：P50 ~14%、P90 ~11%（明顯低於風電的 40%+）
    assert farm.capacity_factor_percent == pytest.approx(14.0)
    assert farm.p90_capacity_factor_percent == pytest.approx(11.0)


def test_solar_generation_is_summer_strong(seeded_db):
    farm = _solar_farm(seeded_db)
    rows = {
        r.period_start.month: r.generated_energy_mwh
        for r in seeded_db.query(GenerationData).filter(
            GenerationData.wind_farm_id == farm.id
        )
    }
    assert len(rows) == 12
    assert rows[7] > rows[1]  # 夏強冬弱，與風電相反


def test_solar_is_contracted_to_a_daytime_customer(seeded_db):
    farm = _solar_farm(seeded_db)
    contracts = list(seeded_db.query(Contract).filter(Contract.wind_farm_id == farm.id))
    assert contracts, "光電應至少有一紙合約"
    industries = {
        seeded_db.get(Customer, c.customer_id).industry
        for c in contracts
        if c.status.value == "active"
    }
    assert industries & DAYTIME_INDUSTRIES


def test_demo_portfolio_beats_its_own_wind_only_baseline(seeded_db):
    """驗收（§9）：示範資料 2024-01 的風光 CFE 要高於只風電。

    「風光」那一段是 ``no_storage_cfe_percent``——``cfe_percent`` 已經含了電池的
    增益,拿它來比會把儲能的功勞算到太陽能頭上。"""
    res = svc.compute_hourly_outcome(seeded_db, "2024-01")
    assert res.wind_only_cfe_percent is not None
    assert res.no_storage_cfe_percent is not None  # 示範資料有一具電池
    wind_solar = res.no_storage_cfe_percent
    assert wind_solar > res.wind_only_cfe_percent
    assert res.uplift_pt == pytest.approx(
        round(wind_solar - res.wind_only_cfe_percent, 2)
    )
    assert res.uplift_pt > 0


def test_solar_contributes_midday_energy_in_the_hourly_view(seeded_db):
    farm = _solar_farm(seeded_db)
    res = svc.compute_hourly_outcome(seeded_db, "2024-01")
    solar_out = next(f for f in res.farms if f.wind_farm_id == farm.id)
    assert solar_out.generated_mwh > 0
    # matched_mwh 只算同一小時直接送到客戶的量,充進電池的另計在 charged_mwh
    # （見 app/matching/storage.py 的能量帳）→ 這一行真的代表「日間客戶用到了」。
    assert solar_out.matched_mwh > 0
    assert solar_out.generated_mwh == pytest.approx(
        solar_out.matched_mwh + (solar_out.charged_mwh or 0.0) + solar_out.surplus_mwh
    )
