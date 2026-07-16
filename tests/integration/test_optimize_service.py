"""Integration test: optimize_service against a seeded in-memory DB."""

from __future__ import annotations

from datetime import date

import pytest

from app.matching.optimizer import OptimizeOptions
from app.models import ConsumptionData, Contract, Customer, GenerationData, WindFarm
from app.models.enums import ContractStatus, GreenTargetType
from app.services import optimize_service


@pytest.fixture()
def seeded(db):
    f1 = WindFarm(
        code="F1", name="F1", installed_capacity_mw=100, feed_in_price_per_kwh=4.0
    )
    f2 = WindFarm(
        code="F2", name="F2", installed_capacity_mw=100, feed_in_price_per_kwh=4.0
    )
    cust = Customer(
        code="K1",
        company_name="K1",
        re_target_percent=50.0,
        green_target_type=GreenTargetType.RE_PERCENT,
    )
    db.add_all([f1, f2, cust])
    db.flush()
    db.add_all(
        [
            GenerationData(
                wind_farm_id=f1.id,
                period_start=date(2024, 1, 1),
                period_end=date(2024, 1, 31),
                generated_energy_mwh=100.0,
            ),
            GenerationData(
                wind_farm_id=f2.id,
                period_start=date(2024, 1, 1),
                period_end=date(2024, 1, 31),
                generated_energy_mwh=100.0,
            ),
            ConsumptionData(
                customer_id=cust.id,
                period_start=date(2024, 1, 1),
                period_end=date(2024, 1, 31),
                consumed_energy_mwh=100.0,
            ),
            Contract(
                contract_number="C1",
                wind_farm_id=f1.id,
                customer_id=cust.id,
                start_date=date(2024, 1, 1),
                end_date=date(2024, 12, 31),
                status=ContractStatus.ACTIVE,
                priority=100,
                contracted_percentage=100.0,
                price_per_kwh=4.3,
            ),
            Contract(
                contract_number="C2",
                wind_farm_id=f2.id,
                customer_id=cust.id,
                start_date=date(2024, 1, 1),
                end_date=date(2024, 12, 31),
                status=ContractStatus.ACTIVE,
                priority=100,
                contracted_percentage=100.0,
                price_per_kwh=4.9,
            ),
        ]
    )
    db.commit()
    return cust


def test_compute_optimized_prefers_high_margin(db, seeded):
    result = optimize_service.compute_optimized(
        db, "2024-01", OptimizeOptions(default_feed_in_price_per_kwh=4.0)
    )
    assert result.period == "2024-01"
    assert result.solver_status == "Optimal"
    by_num = {a.contract_number: a.allocated_mwh for a in result.allocations}
    assert by_num["C2"] == 100.0
    assert by_num["C1"] == 0.0
    assert result.objective_gross_margin_ntd == pytest.approx(90000.0, abs=1.0)
    ct = {c.customer_id: c for c in result.customer_targets}[seeded.id]
    assert ct.re_target_met is True


def test_compute_optimized_empty_period(db, seeded):
    result = optimize_service.compute_optimized(db, "2030-01", OptimizeOptions())
    assert result.objective_gross_margin_ntd == 0.0
    assert all(a.allocated_mwh == 0.0 for a in result.allocations)
