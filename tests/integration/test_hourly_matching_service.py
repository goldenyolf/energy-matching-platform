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
