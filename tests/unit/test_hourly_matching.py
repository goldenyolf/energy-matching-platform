"""Tests for the B7 hourly (24/7 CFE) time-coincident matching engine.

The defining rule: only the per-hour overlap of generation and load counts as
matched green. Surplus in one hour never covers a deficit in another (strict, no
banking). CFE% = Σ matched / Σ consumption.
"""

from __future__ import annotations

import pytest

from app.matching.hourly_matching import (
    HourlyContract,
    HourlyCustomer,
    HourlyFarm,
    match_hourly,
)


def _con(cid, farm, cust, **kw):
    return HourlyContract(
        contract_id=cid,
        contract_number=f"C{cid}",
        wind_farm_id=farm,
        customer_id=cust,
        **kw,
    )


def test_matched_is_hourly_min_of_generation_and_load():
    farms = [HourlyFarm(1, (8.0, 2.0, 6.0))]
    customers = [HourlyCustomer(10, (5.0, 5.0, 5.0))]
    out = match_hourly(farms, customers, [_con(1, 1, 10)])

    assert out.matched_by_hour == pytest.approx([5.0, 2.0, 5.0])
    assert out.total_matched_mwh == pytest.approx(12.0)
    assert out.total_consumption_mwh == pytest.approx(15.0)
    assert out.cfe_percent == pytest.approx(80.0)


def test_strict_no_banking_surplus_does_not_cover_other_hours_deficit():
    # Equal totals (10 vs 10) but perfectly misaligned in time → CFE 0%.
    farms = [HourlyFarm(1, (10.0, 0.0))]
    customers = [HourlyCustomer(10, (0.0, 10.0))]
    out = match_hourly(farms, customers, [_con(1, 1, 10)])

    assert out.matched_by_hour == pytest.approx([0.0, 0.0])
    assert out.cfe_percent == pytest.approx(0.0)
    assert out.farms[0].surplus_mwh == pytest.approx(10.0)
    assert out.customers[0].shortfall_by_hour == pytest.approx([0.0, 10.0])


def test_percentage_cap_limits_hourly_allocation():
    farms = [HourlyFarm(1, (10.0,))]
    customers = [HourlyCustomer(10, (10.0,))]
    out = match_hourly(farms, customers, [_con(1, 1, 10, percentage=30.0)])

    assert out.total_matched_mwh == pytest.approx(3.0)  # 30% of 10


def test_hourly_volume_cap_limits_allocation():
    farms = [HourlyFarm(1, (10.0, 10.0))]
    customers = [HourlyCustomer(10, (10.0, 10.0))]
    out = match_hourly(farms, customers, [_con(1, 1, 10, hourly_cap=(4.0, 1.0))])

    assert out.matched_by_hour == pytest.approx([4.0, 1.0])


def test_priority_orders_allocation_of_scarce_generation():
    farms = [HourlyFarm(1, (6.0,))]
    customers = [HourlyCustomer(10, (5.0,)), HourlyCustomer(20, (5.0,))]
    contracts = [_con(1, 1, 10, priority=1), _con(2, 1, 20, priority=2)]
    out = match_hourly(farms, customers, contracts)

    by_cust = {c.customer_id: c for c in out.customers}
    assert by_cust[10].matched_mwh == pytest.approx(5.0)  # priority 1 served first
    assert by_cust[20].matched_mwh == pytest.approx(1.0)  # gets the remaining 1
    assert by_cust[20].shortfall_by_hour == pytest.approx([4.0])


def test_energy_is_conserved_generation_and_load_balance():
    farms = [HourlyFarm(1, (6.0,))]
    customers = [HourlyCustomer(10, (5.0,)), HourlyCustomer(20, (5.0,))]
    contracts = [_con(1, 1, 10, priority=1), _con(2, 1, 20, priority=2)]
    out = match_hourly(farms, customers, contracts)

    farm = out.farms[0]
    assert farm.matched_mwh + farm.surplus_mwh == pytest.approx(farm.generated_mwh)
    for c in out.customers:
        assert c.matched_mwh + sum(c.shortfall_by_hour) == pytest.approx(
            c.consumption_mwh
        )


def test_empty_inputs_give_zero_cfe_without_error():
    out = match_hourly([], [], [])
    assert out.total_matched_mwh == 0.0
    assert out.cfe_percent == 0.0
