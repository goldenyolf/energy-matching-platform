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
