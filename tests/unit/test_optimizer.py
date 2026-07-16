"""Unit tests for the MILP economic optimizer."""

from __future__ import annotations

from datetime import date

import pytest

from app.matching.engine import (
    ContractInput,
    CustomerDemand,
    FarmSupply,
    match_period,
)
from app.matching.optimizer import OptimizeOptions, optimize_period

START = date(2024, 1, 1)
END = date(2024, 1, 31)
OPTS = OptimizeOptions(default_feed_in_price_per_kwh=4.0)


def _contract(cid, num, farm, cust, price, energy=None, pct=None, priority=100):
    return ContractInput(
        contract_id=cid,
        contract_number=num,
        wind_farm_id=farm,
        customer_id=cust,
        start_date=START,
        end_date=END,
        status="active",
        priority=priority,
        contracted_energy_mwh=energy,
        contracted_percentage=pct,
        price_per_kwh=price,
    )


def _alloc_map(outcome):
    return {a.contract_id: a.allocated_mwh for a in outcome.allocations}


def test_prefers_higher_margin_farm():
    # Two farms can each fully supply the customer; farm 2's contract has more margin.
    farms = [
        FarmSupply(1, 100.0, feed_in_price_per_kwh=4.0),
        FarmSupply(2, 100.0, feed_in_price_per_kwh=4.0),
    ]
    demands = [
        CustomerDemand(1, 100.0, green_target_type="re_percent", re_target_percent=0.0)
    ]
    contracts = [
        _contract(1, "C1", 1, 1, price=4.3),  # margin 0.3
        _contract(2, "C2", 2, 1, price=4.9),  # margin 0.9
    ]
    out = optimize_period("2024-01", START, END, farms, demands, contracts, OPTS)
    alloc = _alloc_map(out)
    assert alloc[2] == 100.0
    assert alloc[1] == 0.0
    # gross margin = 100 MWh * 1000 * 0.9 = 90000 NTD
    assert out.objective_gross_margin_ntd == pytest.approx(90000.0, abs=1.0)
    assert out.solver_status == "Optimal"


def test_re_hard_constraint_met_when_feasible():
    farms = [
        FarmSupply(1, 100.0, feed_in_price_per_kwh=4.0),
        FarmSupply(2, 100.0, feed_in_price_per_kwh=4.0),
    ]
    demands = [
        CustomerDemand(1, 100.0, green_target_type="re_percent", re_target_percent=80.0)
    ]
    # Only the low-margin farm can serve; RE target must still be met.
    contracts = [_contract(1, "C1", 1, 1, price=4.1)]
    out = optimize_period("2024-01", START, END, farms, demands, contracts, OPTS)
    ct = {c.customer_id: c for c in out.customer_targets}[1]
    assert ct.re_target_mwh == 80.0
    assert ct.allocated_mwh >= 80.0 - 1e-6
    assert ct.re_target_met is True
    assert ct.re_shortfall_mwh == 0.0


def test_re_soft_fallback_when_infeasible():
    # Demand 100, target 80, but only 50 MWh of supply exists → shortfall 30.
    farms = [FarmSupply(1, 50.0, feed_in_price_per_kwh=4.0)]
    demands = [
        CustomerDemand(1, 100.0, green_target_type="re_percent", re_target_percent=80.0)
    ]
    contracts = [_contract(1, "C1", 1, 1, price=4.5)]
    out = optimize_period("2024-01", START, END, farms, demands, contracts, OPTS)
    ct = {c.customer_id: c for c in out.customer_targets}[1]
    assert ct.allocated_mwh == pytest.approx(50.0, abs=1e-6)
    assert ct.re_shortfall_mwh == pytest.approx(30.0, abs=1e-6)
    assert ct.re_target_met is False


def test_energy_target_type():
    farms = [FarmSupply(1, 100.0, feed_in_price_per_kwh=4.0)]
    demands = [
        CustomerDemand(1, 100.0, green_target_type="energy", target_energy_mwh=25.0)
    ]
    contracts = [_contract(1, "C1", 1, 1, price=4.5)]
    out = optimize_period("2024-01", START, END, farms, demands, contracts, OPTS)
    ct = {c.customer_id: c for c in out.customer_targets}[1]
    assert ct.re_target_mwh == 25.0
    assert ct.allocated_mwh >= 25.0 - 1e-6


def test_min_sites_forces_spread():
    # Customer could be fully served by farm 2 alone (higher margin), but min_sites=2
    # forces using both farms.
    farms = [
        FarmSupply(1, 100.0, feed_in_price_per_kwh=4.0),
        FarmSupply(2, 100.0, feed_in_price_per_kwh=4.0),
    ]
    demands = [
        CustomerDemand(
            1, 100.0, green_target_type="re_percent", re_target_percent=100.0
        )
    ]
    contracts = [
        _contract(1, "C1", 1, 1, price=4.3),
        _contract(2, "C2", 2, 1, price=4.9),
    ]
    opts = OptimizeOptions(min_sites_per_customer=2, default_feed_in_price_per_kwh=4.0)
    out = optimize_period("2024-01", START, END, farms, demands, contracts, opts)
    ct = {c.customer_id: c for c in out.customer_targets}[1]
    assert ct.sites_used == 2
    assert ct.site_shortfall == 0


def test_min_sites_shortfall_when_not_enough_farms():
    farms = [FarmSupply(1, 100.0, feed_in_price_per_kwh=4.0)]
    demands = [
        CustomerDemand(
            1, 100.0, green_target_type="re_percent", re_target_percent=100.0
        )
    ]
    contracts = [_contract(1, "C1", 1, 1, price=4.5)]
    opts = OptimizeOptions(min_sites_per_customer=3, default_feed_in_price_per_kwh=4.0)
    out = optimize_period("2024-01", START, END, farms, demands, contracts, opts)
    ct = {c.customer_id: c for c in out.customer_targets}[1]
    # only 1 eligible contract → min_sites clamped to 1 → no shortfall
    assert ct.sites_used == 1
    assert ct.site_shortfall == 0


def test_min_site_allocation_percent_excludes_slivers():
    # Farm 2 caps at 5 MWh (5% of demand); floor 10% → farm 2 cannot be used.
    farms = [
        FarmSupply(1, 100.0, feed_in_price_per_kwh=4.0),
        FarmSupply(2, 100.0, feed_in_price_per_kwh=4.0),
    ]
    demands = [
        CustomerDemand(
            1, 100.0, green_target_type="re_percent", re_target_percent=100.0
        )
    ]
    contracts = [
        _contract(1, "C1", 1, 1, price=4.3),
        _contract(2, "C2", 2, 1, price=4.9, energy=5.0),  # capped at 5 MWh
    ]
    opts = OptimizeOptions(
        min_site_allocation_percent=10.0, default_feed_in_price_per_kwh=4.0
    )
    out = optimize_period("2024-01", START, END, farms, demands, contracts, opts)
    alloc = _alloc_map(out)
    assert alloc[2] == 0.0  # sliver excluded by the floor
    assert alloc[1] == 100.0


def test_deterministic_same_and_shuffled_input():
    farms = [
        FarmSupply(1, 100.0, feed_in_price_per_kwh=4.0),
        FarmSupply(2, 80.0, feed_in_price_per_kwh=4.2),
        FarmSupply(3, 60.0, feed_in_price_per_kwh=3.8),
    ]
    demands = [
        CustomerDemand(
            1, 120.0, green_target_type="re_percent", re_target_percent=50.0
        ),
        CustomerDemand(2, 90.0, green_target_type="re_percent", re_target_percent=70.0),
    ]
    contracts = [
        _contract(1, "C1", 1, 1, price=4.6),
        _contract(2, "C2", 2, 1, price=4.9),
        _contract(3, "C3", 2, 2, price=4.7),
        _contract(4, "C4", 3, 2, price=5.1),
    ]
    a = optimize_period("2024-01", START, END, farms, demands, contracts, OPTS)
    b = optimize_period(
        "2024-01", START, END, farms, demands, list(reversed(contracts)), OPTS
    )
    assert _alloc_map(a) == _alloc_map(b)


def test_optimizer_not_worse_than_greedy():
    farms = [
        FarmSupply(1, 100.0, feed_in_price_per_kwh=4.0),
        FarmSupply(2, 100.0, feed_in_price_per_kwh=4.0),
    ]
    demands = [
        CustomerDemand(1, 150.0, green_target_type="re_percent", re_target_percent=0.0)
    ]
    # Greedy by priority would serve C1 (low margin) first; optimizer prefers C2.
    contracts = [
        _contract(1, "C1", 1, 1, price=4.2, priority=1),
        _contract(2, "C2", 2, 1, price=4.9, priority=2),
    ]

    def margin_of(alloc_map):
        m = 0.0
        for c in contracts:
            m += alloc_map.get(c.contract_id, 0.0) * 1000.0 * (c.price_per_kwh - 4.0)
        return m

    greedy = match_period("2024-01", START, END, farms, demands, contracts)
    opt = optimize_period("2024-01", START, END, farms, demands, contracts, OPTS)
    assert margin_of(_alloc_map(opt)) >= margin_of(_alloc_map(greedy)) - 1e-6


def test_empty_contracts_no_crash():
    farms = [FarmSupply(1, 100.0)]
    demands = [CustomerDemand(1, 100.0)]
    out = optimize_period("2024-01", START, END, farms, demands, [], OPTS)
    assert out.allocations == []
    assert out.objective_gross_margin_ntd == 0.0
    assert out.farm_summaries[0].unallocated_mwh == 100.0


def test_ineligible_contract_skipped():
    farms = [FarmSupply(1, 100.0, feed_in_price_per_kwh=4.0)]
    demands = [CustomerDemand(1, 100.0)]
    contracts = [
        ContractInput(
            contract_id=9,
            contract_number="X",
            wind_farm_id=1,
            customer_id=1,
            start_date=START,
            end_date=END,
            status="expired",
            price_per_kwh=4.5,
        )
    ]
    out = optimize_period("2024-01", START, END, farms, demands, contracts, OPTS)
    assert out.allocations == []
    assert len(out.skipped) == 1
    assert out.skipped[0].contract_id == 9
