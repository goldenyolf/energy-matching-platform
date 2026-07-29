"""Slot profile generator: sums to monthly, mutually exclusive, deterministic;
and the monthly engine still totals correctly on slot data."""

from __future__ import annotations

from datetime import date

from app.models import ConsumptionData, Contract, Customer, GenerationData, WindFarm
from app.models.enums import ContractStatus
from app.services.matching_service import compute_outcome
from scripts.generate_slot_profiles import split_profiles


def _seed_monthly(db):
    f = WindFarm(
        code="F1", name="F1", installed_capacity_mw=100, feed_in_price_per_kwh=4.0
    )
    cust = Customer(code="K1", company_name="K1", re_target_percent=100.0)
    db.add_all([f, cust])
    db.flush()
    db.add(
        GenerationData(
            wind_farm_id=f.id,
            period_start=date(2024, 1, 1),
            period_end=date(2024, 1, 31),
            generated_energy_mwh=100.0,
        )
    )
    db.add(
        ConsumptionData(
            customer_id=cust.id,
            period_start=date(2024, 1, 1),
            period_end=date(2024, 1, 31),
            consumed_energy_mwh=80.0,
        )
    )
    db.add(
        Contract(
            contract_number="C1",
            wind_farm_id=f.id,
            customer_id=cust.id,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
            status=ContractStatus.ACTIVE,
            priority=100,
            contracted_percentage=100.0,
            price_per_kwh=4.8,
        )
    )
    db.commit()
    return f, cust


def test_split_sums_to_monthly_and_mutually_exclusive(db):
    f, cust = _seed_monthly(db)
    split_profiles(db)
    gens = db.query(GenerationData).filter(GenerationData.wind_farm_id == f.id).all()
    # monthly row replaced by 3 slot rows summing to 100
    assert all(g.time_slot is not None for g in gens)
    assert len(gens) == 3
    assert round(sum(g.generated_energy_mwh for g in gens), 6) == 100.0


def test_monthly_engine_still_totals_on_slot_data(db):
    f, cust = _seed_monthly(db)
    split_profiles(db)
    outcome = compute_outcome(db, "2024-01")
    farm = {s.farm_id: s for s in outcome.farm_summaries}[f.id]
    assert farm.generated_mwh == 100.0  # monthly engine sums slot rows back to monthly


def _seed_solar_monthly(db):
    f = WindFarm(
        code="S1",
        name="S1",
        installed_capacity_mw=50,
        feed_in_price_per_kwh=4.0,
        farm_type="solar",
    )
    db.add(f)
    db.flush()
    db.add(
        GenerationData(
            wind_farm_id=f.id,
            period_start=date(2024, 1, 1),
            period_end=date(2024, 1, 31),
            generated_energy_mwh=100.0,
        )
    )
    db.commit()
    return f


def test_solar_splits_into_daytime_slots_with_no_off_peak(db):
    f = _seed_solar_monthly(db)
    split_profiles(db)
    by_slot = {
        g.time_slot.value: g.generated_energy_mwh
        for g in db.query(GenerationData).filter(GenerationData.wind_farm_id == f.id)
    }
    assert round(sum(by_slot.values()), 6) == 100.0
    # 太陽能夜間不發電：離峰≈0，尖峰＋半尖峰吃下幾乎全部。
    assert by_slot["off_peak"] <= 2.0
    assert by_slot["peak"] + by_slot["half_peak"] >= 98.0


def test_wind_keeps_its_off_peak_heavy_split(db):
    f, _cust = _seed_monthly(db)
    split_profiles(db)
    by_slot = {
        g.time_slot.value: g.generated_energy_mwh
        for g in db.query(GenerationData).filter(GenerationData.wind_farm_id == f.id)
    }
    assert by_slot["off_peak"] > by_slot["peak"]


def test_deterministic(db):
    f, cust = _seed_monthly(db)
    split_profiles(db)
    first = sorted(
        (g.time_slot.value, g.generated_energy_mwh)
        for g in db.query(GenerationData).all()
    )
    # re-running on already-split data is idempotent (no monthly rows remain to split)
    split_profiles(db)
    second = sorted(
        (g.time_slot.value, g.generated_energy_mwh)
        for g in db.query(GenerationData).all()
    )
    assert first == second
