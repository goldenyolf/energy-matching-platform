"""Integration test: hourly_matching_service against a seeded DB."""

from __future__ import annotations

from datetime import date

import pytest

from app.models import ConsumptionData, Contract, Customer, GenerationData, WindFarm
from app.models.enums import ContractStatus
from app.services import hourly_matching_service as svc


@pytest.fixture()
def seeded(db):
    # A night-strong wind farm and a 24h-flat semiconductor load.
    farm = WindFarm(
        code="F1", name="風場一", installed_capacity_mw=100, feed_in_price_per_kwh=4.0
    )
    cust = Customer(
        code="K1", company_name="用電廠一", industry="半導體", re_target_percent=100.0
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


def test_hourly_result_is_modeled_and_has_24_hours(seeded):
    db, _, _ = seeded
    res = svc.compute_hourly_outcome(db, "2024-01")
    assert res.modeled is True
    assert res.hours == 24
    assert len(res.matched_by_hour) == 24


def test_period_total_is_preserved(seeded):
    db, _, _ = seeded
    res = svc.compute_hourly_outcome(db, "2024-01")
    # Σ hourly consumption == the period total (可對帳).
    assert sum(res.consumption_by_hour) == pytest.approx(1000.0)
    assert sum(res.generation_by_hour) == pytest.approx(1000.0)


def test_hourly_cfe_is_below_paper_re_for_misaligned_shapes(seeded):
    # Night-strong wind vs flat baseload never overlaps perfectly, so the true
    # 24/7 CFE must sit strictly below the paper (monthly-netting) figure.
    db, _, _ = seeded
    res = svc.compute_hourly_outcome(db, "2024-01")
    assert res.paper_re_percent == pytest.approx(100.0)  # equal totals net to 100%
    assert res.cfe_percent < res.paper_re_percent
    assert 0.0 < res.cfe_percent < 100.0


def test_customer_breakdown_carries_cfe_and_curves(seeded):
    db, _, cust = seeded
    res = svc.compute_hourly_outcome(db, "2024-01")
    c = next(x for x in res.customers if x.customer_id == cust.id)
    assert c.industry == "半導體"
    # load == matched + shortfall, hour by hour.
    load = [m + s for m, s in zip(c.matched_by_hour, c.shortfall_by_hour, strict=True)]
    assert sum(load) == pytest.approx(c.consumption_mwh)
    assert c.cfe_percent == pytest.approx(res.cfe_percent)


def test_customer_id_filter_narrows_the_customers_list(seeded):
    db, _, cust = seeded
    res = svc.compute_hourly_outcome(db, "2024-01", customer_id=cust.id)
    assert [c.customer_id for c in res.customers] == [cust.id]

    empty = svc.compute_hourly_outcome(db, "2024-01", customer_id=99999)
    assert empty.customers == []


@pytest.fixture()
def seeded_solar(db):
    """A7: a solar site plus a day-shift load, no interval data (modeled path)."""
    farm = WindFarm(
        code="S1",
        name="示範地面型光電",
        installed_capacity_mw=80,
        feed_in_price_per_kwh=4.0,
        farm_type="solar",
    )
    cust = Customer(
        code="K2", company_name="用電廠二", industry="電源管理", re_target_percent=100.0
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
            contract_number="CT-S1",
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
def seeded_mixed(db):
    """B4: one wind site + one solar site feeding the same daytime customer."""
    wind = WindFarm(
        code="F1", name="風場一", installed_capacity_mw=100, feed_in_price_per_kwh=4.0
    )
    solar = WindFarm(
        code="S1",
        name="示範地面型光電",
        installed_capacity_mw=80,
        feed_in_price_per_kwh=4.0,
        farm_type="solar",
    )
    cust = Customer(
        code="K2", company_name="用電廠二", industry="電源管理", re_target_percent=100.0
    )
    db.add_all([wind, solar, cust])
    db.flush()
    for farm in (wind, solar):
        db.add(
            GenerationData(
                wind_farm_id=farm.id,
                period_start=date(2024, 1, 1),
                period_end=date(2024, 1, 31),
                generated_energy_mwh=600.0,
            )
        )
        db.add(
            Contract(
                contract_number=f"CT-{farm.code}",
                wind_farm_id=farm.id,
                customer_id=cust.id,
                start_date=date(2024, 1, 1),
                end_date=date(2030, 1, 1),
                status=ContractStatus.ACTIVE,
                price_per_kwh=4.5,
            )
        )
    db.add(
        ConsumptionData(
            customer_id=cust.id,
            period_start=date(2024, 1, 1),
            period_end=date(2024, 1, 31),
            consumed_energy_mwh=1200.0,
        )
    )
    db.commit()
    return db, wind, solar, cust


def test_adding_solar_lifts_cfe_above_the_wind_only_baseline(seeded_mixed):
    """風光互補：同樣的負載，加上正午 bell 之後逐時 CFE 應該真的變高。"""
    db, _, _, _ = seeded_mixed
    res = svc.compute_hourly_outcome(db, "2024-01")
    assert res.wind_only_cfe_percent is not None
    assert res.cfe_percent > res.wind_only_cfe_percent
    assert res.uplift_pt == pytest.approx(
        round(res.cfe_percent - res.wind_only_cfe_percent, 2)
    )
    assert res.uplift_pt > 0


def test_wind_only_baseline_drops_the_solar_site_and_its_contract(seeded_mixed):
    """基準線＝把光電案場與它的合約整個拿掉，負載（分母）維持不變。"""
    db, wind, solar, _ = seeded_mixed
    res = svc.compute_hourly_outcome(db, "2024-01")

    db.query(Contract).filter(Contract.wind_farm_id == solar.id).delete()
    db.query(GenerationData).filter(GenerationData.wind_farm_id == solar.id).delete()
    db.query(WindFarm).filter(WindFarm.id == solar.id).delete()
    db.commit()

    without_solar = svc.compute_hourly_outcome(db, "2024-01")
    assert without_solar.cfe_percent == pytest.approx(res.wind_only_cfe_percent)
    assert without_solar.wind_only_cfe_percent is None  # 沒有光電就沒有對照組
    assert without_solar.uplift_pt is None
    assert wind.id  # 風場本身沒被動到


def test_no_uplift_reported_when_there_is_no_solar(seeded):
    db, _, _ = seeded
    res = svc.compute_hourly_outcome(db, "2024-01")
    assert res.wind_only_cfe_percent is None
    assert res.uplift_pt is None
    assert res.solar_generation_by_hour is None


def test_customer_rows_carry_their_own_uplift(seeded_mixed):
    """系統級增益會被沒簽光電的大客戶稀釋,真正的證據在簽了光電的那一家。"""
    db, _, _, cust = seeded_mixed
    res = svc.compute_hourly_outcome(db, "2024-01")
    c = next(x for x in res.customers if x.customer_id == cust.id)
    assert c.wind_only_cfe_percent is not None
    assert c.cfe_percent > c.wind_only_cfe_percent
    assert c.uplift_pt == pytest.approx(
        round(c.cfe_percent - c.wind_only_cfe_percent, 2)
    )


def test_customer_rows_have_no_uplift_without_solar(seeded):
    db, _, _ = seeded
    res = svc.compute_hourly_outcome(db, "2024-01")
    assert all(c.wind_only_cfe_percent is None for c in res.customers)
    assert all(c.uplift_pt is None for c in res.customers)


def test_generation_curve_carries_the_solar_share_for_stacking(seeded_mixed):
    """前端要畫「風 + 光」堆疊，所以總發電之外還要拿得到光電那一層。"""
    db, _, _, _ = seeded_mixed
    res = svc.compute_hourly_outcome(db, "2024-01")
    solar = res.solar_generation_by_hour
    assert solar is not None and len(solar) == 24
    assert sum(solar) == pytest.approx(600.0)  # 光電案場的月發電量
    assert solar[2] == pytest.approx(0.0)  # 夜間那層是平的
    assert solar[12] > 0.0
    # 光電是總發電的一部分，任何小時都不能超過總量。
    for s, total in zip(solar, res.generation_by_hour, strict=True):
        assert s <= total + 1e-9


def test_modeled_solar_generation_follows_the_daytime_bell(seeded_solar):
    db, _, _ = seeded_solar
    res = svc.compute_hourly_outcome(db, "2024-01")
    assert res.source == "modeled"
    assert sum(res.generation_by_hour) == pytest.approx(1000.0)
    assert res.generation_by_hour[2] == pytest.approx(0.0)  # 夜間不發電
    assert res.generation_by_hour[22] == pytest.approx(0.0)
    assert res.generation_by_hour.index(max(res.generation_by_hour)) in (11, 12, 13)


def test_solar_matches_the_daytime_load_it_is_contracted_to(seeded_solar):
    db, _, _ = seeded_solar
    res = svc.compute_hourly_outcome(db, "2024-01")
    # 日間負載 × 正午 bell 有實質重疊，但夜間用電無綠電可對 → 0 < CFE < 帳面。
    assert 0.0 < res.cfe_percent < res.paper_re_percent
    assert res.matched_by_hour[2] == pytest.approx(0.0)
    assert res.matched_by_hour[12] > 0.0
