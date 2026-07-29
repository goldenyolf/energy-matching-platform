"""B5：逐時服務接上客戶側儲能。"""

from __future__ import annotations

from datetime import date

import pytest

from app.models import (
    Battery,
    ConsumptionData,
    Contract,
    Customer,
    GenerationData,
    WindFarm,
)
from app.models.enums import ContractStatus
from app.services import hourly_matching_service as svc


@pytest.fixture()
def seeded_storage(db):
    """夜強日弱的風場 × 日間型負載 → 夜間外溢、白天缺口,正好給電池發揮。"""
    farm = WindFarm(
        code="F1", name="風場一", installed_capacity_mw=100, feed_in_price_per_kwh=4.0
    )
    cust = Customer(
        code="K1", company_name="用電廠一", industry="電源管理", re_target_percent=100.0
    )
    db.add_all([farm, cust])
    db.flush()
    db.add(
        GenerationData(
            wind_farm_id=farm.id,
            period_start=date(2024, 1, 1),
            period_end=date(2024, 1, 31),
            generated_energy_mwh=1000.0,
        )
    )
    db.add(
        ConsumptionData(
            customer_id=cust.id,
            period_start=date(2024, 1, 1),
            period_end=date(2024, 1, 31),
            consumed_energy_mwh=1000.0,
        )
    )
    db.add(
        Contract(
            contract_number="CT-1",
            wind_farm_id=farm.id,
            customer_id=cust.id,
            start_date=date(2024, 1, 1),
            end_date=date(2030, 1, 1),
            status=ContractStatus.ACTIVE,
            price_per_kwh=4.5,
        )
    )
    db.commit()
    return db, farm, cust


@pytest.fixture()
def seeded_wind_solar_storage(db):
    """風 + 光 + 同一客戶儲能:三段式讀數（只風電→風光→風光＋儲）必須互不重疊。"""
    wind = WindFarm(
        code="F1", name="風場一", installed_capacity_mw=100, feed_in_price_per_kwh=4.0
    )
    solar = WindFarm(
        code="F2",
        name="光電場一",
        installed_capacity_mw=50,
        feed_in_price_per_kwh=4.2,
        farm_type="solar",
    )
    cust = Customer(
        code="K1", company_name="用電廠一", industry="電源管理", re_target_percent=100.0
    )
    db.add_all([wind, solar, cust])
    db.flush()
    db.add(
        GenerationData(
            wind_farm_id=wind.id,
            period_start=date(2024, 1, 1),
            period_end=date(2024, 1, 31),
            generated_energy_mwh=1000.0,
        )
    )
    db.add(
        GenerationData(
            wind_farm_id=solar.id,
            period_start=date(2024, 1, 1),
            period_end=date(2024, 1, 31),
            generated_energy_mwh=500.0,
        )
    )
    db.add(
        ConsumptionData(
            customer_id=cust.id,
            period_start=date(2024, 1, 1),
            period_end=date(2024, 1, 31),
            consumed_energy_mwh=1000.0,
        )
    )
    db.add(
        Contract(
            contract_number="CT-1",
            wind_farm_id=wind.id,
            customer_id=cust.id,
            start_date=date(2024, 1, 1),
            end_date=date(2030, 1, 1),
            status=ContractStatus.ACTIVE,
            price_per_kwh=4.5,
        )
    )
    db.add(
        Contract(
            contract_number="CT-2",
            wind_farm_id=solar.id,
            customer_id=cust.id,
            start_date=date(2024, 1, 1),
            end_date=date(2030, 1, 1),
            status=ContractStatus.ACTIVE,
            price_per_kwh=4.3,
        )
    )
    db.add(
        Battery(
            code="BAT-1",
            customer_id=cust.id,
            name="示範儲能",
            energy_capacity_mwh=200.0,
            power_mw=50.0,
        )
    )
    db.commit()
    return db, cust


def test_no_battery_means_no_storage_readout(seeded_storage):
    db, _, _ = seeded_storage
    res = svc.compute_hourly_outcome(db, "2024-01")
    assert res.no_storage_cfe_percent is None
    assert res.storage_uplift_pt is None
    assert res.soc_by_hour is None
    assert all(c.storage_uplift_pt is None for c in res.customers)


def test_a_battery_lifts_cfe_and_cuts_spill(seeded_storage):
    db, _, cust = seeded_storage
    before = svc.compute_hourly_outcome(db, "2024-01")

    db.add(
        Battery(
            code="BAT-1",
            customer_id=cust.id,
            name="示範儲能",
            energy_capacity_mwh=200.0,
            power_mw=50.0,
        )
    )
    db.commit()
    after = svc.compute_hourly_outcome(db, "2024-01")

    assert after.cfe_percent > before.cfe_percent
    assert after.total_surplus_mwh < before.total_surplus_mwh
    assert after.total_shortfall_mwh < before.total_shortfall_mwh
    # 無儲對照 = 加電池前的數字
    assert after.no_storage_cfe_percent == pytest.approx(before.cfe_percent)
    assert after.storage_uplift_pt == pytest.approx(
        round(after.cfe_percent - before.cfe_percent, 2)
    )


def test_storage_curves_respect_the_battery_limits(seeded_storage):
    db, _, cust = seeded_storage
    db.add(
        Battery(
            code="BAT-1",
            customer_id=cust.id,
            name="示範儲能",
            energy_capacity_mwh=200.0,
            power_mw=50.0,
        )
    )
    db.commit()
    res = svc.compute_hourly_outcome(db, "2024-01")

    assert res.soc_by_hour is not None and len(res.soc_by_hour) == 24
    assert max(res.soc_by_hour) <= 200.0 + 1e-6
    assert res.discharged_by_hour is not None
    assert sum(res.discharged_by_hour) > 0.0
    assert sum(res.charged_by_hour) > 0.0


def test_customer_rows_carry_their_own_storage_uplift(seeded_storage):
    db, _, cust = seeded_storage
    db.add(
        Battery(
            code="BAT-1",
            customer_id=cust.id,
            name="示範儲能",
            energy_capacity_mwh=200.0,
            power_mw=50.0,
        )
    )
    db.commit()
    res = svc.compute_hourly_outcome(db, "2024-01")

    c = next(x for x in res.customers if x.customer_id == cust.id)
    assert c.no_storage_cfe_percent is not None
    assert c.cfe_percent > c.no_storage_cfe_percent
    assert c.storage_uplift_pt == pytest.approx(
        round(c.cfe_percent - c.no_storage_cfe_percent, 2)
    )


def test_storage_also_works_on_the_real_interval_path(seeded_storage):
    """interval 模式跑的是 744 個小時桶,SOC 必須跨日連續、且維持單顆電池的尺度。"""
    from scripts.generate_interval_data import generate

    db, _, cust = seeded_storage
    db.add(
        Battery(
            code="BAT-1",
            customer_id=cust.id,
            name="示範儲能",
            energy_capacity_mwh=200.0,
            power_mw=50.0,
        )
    )
    db.commit()
    generate(db, "2024-01")

    res = svc.compute_hourly_outcome(db, "2024-01")
    assert res.source == "interval"
    assert res.storage_uplift_pt is not None and res.storage_uplift_pt > 0
    # SOC 是日均、不是 31 天的加總 → 不得超過單顆電池的容量。
    assert res.soc_by_hour is not None
    assert max(res.soc_by_hour) <= 200.0 + 1e-6


def test_customer_uplift_segments_stay_disjoint_with_wind_solar_and_storage(
    seeded_wind_solar_storage,
):
    """迴歸測試：uplift_pt 曾誤用加了電池之後的 cfe_percent 當基準,把儲能的增益也
    算進太陽能頭上,兩段重疊。修正後 uplift_pt 只該用「加電池之前」的客戶 CFE。"""
    db, cust = seeded_wind_solar_storage
    res = svc.compute_hourly_outcome(db, "2024-01")

    c = next(x for x in res.customers if x.customer_id == cust.id)
    assert c.wind_only_cfe_percent is not None
    assert c.no_storage_cfe_percent is not None
    # uplift_pt = 太陽能單獨的貢獻 = 無儲對照 − 只風電對照
    assert c.uplift_pt == pytest.approx(
        round(c.no_storage_cfe_percent - c.wind_only_cfe_percent, 2)
    )
    # storage_uplift_pt = 電池單獨的貢獻 = 最終 − 無儲對照
    assert c.storage_uplift_pt == pytest.approx(
        round(c.cfe_percent - c.no_storage_cfe_percent, 2)
    )
    # 兩段互斥且完整覆蓋:加總等於總增益
    assert c.uplift_pt + c.storage_uplift_pt == pytest.approx(
        round(c.cfe_percent - c.wind_only_cfe_percent, 2)
    )


def test_a_battery_whose_owner_has_no_load_cannot_shrink_the_spill(seeded_storage):
    """幽靈電池：主人這段期間完全沒有用電 → 它永遠放不出電,也就不該吃掉任何外溢。
    否則 KPI 的「外溢」會憑空變小,而沒有任何一度電送到任何人手上。"""
    db, _, _ = seeded_storage
    before = svc.compute_hourly_outcome(db, "2024-01")

    ghost = Customer(code="GHOST", company_name="沒有用電的公司", industry="電子")
    db.add(ghost)
    db.flush()
    db.add(
        Battery(
            code="BAT-GHOST",
            customer_id=ghost.id,
            name="幽靈電池",
            energy_capacity_mwh=5000.0,
            power_mw=5000.0,
        )
    )
    db.commit()
    after = svc.compute_hourly_outcome(db, "2024-01")

    assert after.total_surplus_mwh == pytest.approx(before.total_surplus_mwh)
    assert after.total_matched_mwh == pytest.approx(before.total_matched_mwh)
    assert after.total_charged_mwh == pytest.approx(0.0)
    assert after.storage_uplift_pt == pytest.approx(0.0)


def test_the_post_storage_energy_accounting_identity_holds(seeded_storage):
    """儲能之後,每一度發出來的電只落在三個桶之一：直供客戶、充進電池、外溢。
    充進電池的又分成「真的送出去了」與「損耗＋期末殘留」——後者誰也沒用到,
    既不能算進案場的 matched,也不能讓外溢替它消失。"""
    db, _, cust = seeded_storage
    db.add(
        Battery(
            code="BAT-1",
            customer_id=cust.id,
            name="示範儲能",
            energy_capacity_mwh=200.0,
            power_mw=50.0,
        )
    )
    db.commit()
    r = svc.compute_hourly_outcome(db, "2024-01")

    generated = sum(f.generated_mwh for f in r.farms)
    direct = sum(f.matched_mwh for f in r.farms)
    charged = sum(f.charged_mwh or 0.0 for f in r.farms)
    spilled = sum(f.surplus_mwh for f in r.farms)
    assert generated == pytest.approx(direct + charged + spilled)
    assert charged == pytest.approx(r.total_charged_mwh)
    assert spilled == pytest.approx(r.total_surplus_mwh)
    # 送到客戶手上的 = 案場當下直供 + 電池後來送出
    assert r.total_matched_mwh == pytest.approx(direct + r.total_discharged_mwh)
    # 進得去出不來的那一段（往返損耗 + 期末殘留）確實存在,而且被單獨報出來
    assert r.total_charged_mwh > r.total_discharged_mwh
