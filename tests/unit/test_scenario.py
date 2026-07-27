"""Unit tests for the greenfield 'what-if' scenario optimizer.

Unlike the contract-driven optimizer, this one allocates ANY farm to ANY
customer (hypothetical pairings) under a single assumed transfer price, subject
to per-customer RE targets. See app/matching/scenario.py.
"""

from __future__ import annotations

import pytest

from app.matching.engine import CustomerDemand, FarmSupply
from app.matching.scenario import ScenarioOptions, optimize_scenario

OPTS = ScenarioOptions(
    assumed_transfer_price_per_kwh=5.0, default_feed_in_price_per_kwh=4.0
)


def _demand(cid, cons, target):
    return CustomerDemand(
        cid, cons, green_target_type="re_percent", re_target_percent=target
    )


def _alloc(out):
    return {(a.wind_farm_id, a.customer_id): a.allocated_mwh for a in out.allocations}


def test_allocates_without_any_contract():
    # Greenfield: a farm and a customer with NO contract between them still match.
    farms = [FarmSupply(1, 100.0, feed_in_price_per_kwh=4.0)]
    demands = [_demand(1, 100.0, 100.0)]
    out = optimize_scenario("2024-01", farms, demands, OPTS)
    a = _alloc(out)
    assert a[(1, 1)] == pytest.approx(100.0, abs=1e-6)
    assert out.allocations[0].has_contract is False
    assert out.solver_status == "Optimal"
    ct = {c.customer_id: c for c in out.customer_targets}[1]
    assert ct.re_target_met is True


def test_prefers_cheaper_feedin_farm():
    # Single transfer price → cheaper feed-in = higher margin. Fill the customer's
    # RE need from the cheaper farm first, then the pricier one.
    farms = [
        FarmSupply(1, 60.0, feed_in_price_per_kwh=4.0),  # margin 1.0
        FarmSupply(2, 100.0, feed_in_price_per_kwh=4.5),  # margin 0.5
    ]
    demands = [_demand(1, 100.0, 100.0)]  # needs 100 MWh green
    out = optimize_scenario("2024-01", farms, demands, OPTS)
    a = _alloc(out)
    assert a[(1, 1)] == pytest.approx(60.0, abs=1e-6)
    assert a[(2, 1)] == pytest.approx(40.0, abs=1e-6)


def test_allocation_capped_at_re_target_not_consumption():
    # Green is abundant (200 available) but the customer's RE target is 50% of
    # 100 MWh = 50 MWh. Allocation must stop at 50 (RE% ≤ target), never fill the
    # full consumption; the rest stays as farm surplus.
    farms = [FarmSupply(1, 200.0, feed_in_price_per_kwh=4.0)]
    demands = [_demand(1, 100.0, 50.0)]
    out = optimize_scenario("2024-01", farms, demands, OPTS)
    ct = {c.customer_id: c for c in out.customer_targets}[1]
    assert ct.allocated_mwh == pytest.approx(50.0, abs=1e-6)
    assert ct.re_target_met is True
    fs = {s.farm_id: s for s in out.farm_summaries}[1]
    assert fs.unallocated_mwh == pytest.approx(150.0, abs=1e-6)  # green not force-sold


def test_re_target_forces_loss_making_farm():
    # Transfer price 4.0 but feed-in 4.5 → margin -0.5. With no RE floor the
    # optimizer allocates nothing; an 80% RE target forces exactly 80 MWh (it
    # will not sell more than the target at a loss).
    farms = [FarmSupply(1, 100.0, feed_in_price_per_kwh=4.5)]
    demands = [_demand(1, 100.0, 80.0)]
    opts = ScenarioOptions(
        assumed_transfer_price_per_kwh=4.0, default_feed_in_price_per_kwh=4.0
    )
    out = optimize_scenario("2024-01", farms, demands, opts)
    a = _alloc(out)
    assert a[(1, 1)] == pytest.approx(80.0, abs=1e-6)
    ct = {c.customer_id: c for c in out.customer_targets}[1]
    assert ct.re_target_met is True


def test_supply_shortfall_when_insufficient():
    farms = [FarmSupply(1, 50.0, feed_in_price_per_kwh=4.0)]
    demands = [_demand(1, 100.0, 100.0)]
    out = optimize_scenario("2024-01", farms, demands, OPTS)
    ct = {c.customer_id: c for c in out.customer_targets}[1]
    assert ct.allocated_mwh == pytest.approx(50.0, abs=1e-6)
    assert ct.re_shortfall_mwh == pytest.approx(50.0, abs=1e-6)
    assert ct.re_target_met is False


def test_has_contract_flag_marks_real_pairs():
    farms = [
        FarmSupply(1, 60.0, feed_in_price_per_kwh=4.0),  # cheaper → used first
        FarmSupply(2, 100.0, feed_in_price_per_kwh=4.2),
    ]
    demands = [_demand(1, 100.0, 100.0)]  # needs 100 MWh green → uses both farms
    out = optimize_scenario("2024-01", farms, demands, OPTS, contract_pairs={(2, 1)})
    flags = {(a.wind_farm_id, a.customer_id): a.has_contract for a in out.allocations}
    assert flags[(1, 1)] is False  # hypothetical (no contract)
    assert flags[(2, 1)] is True  # real contract exists


def test_empty_inputs_no_crash():
    out = optimize_scenario("2024-01", [], [], OPTS)
    assert out.allocations == []
    assert out.objective_gross_margin_ntd == 0.0
    assert out.solver_status == "Optimal"

    farms = [FarmSupply(1, 100.0, feed_in_price_per_kwh=4.0)]
    out2 = optimize_scenario("2024-01", farms, [], OPTS)
    assert out2.allocations == []
    assert out2.farm_summaries[0].unallocated_mwh == pytest.approx(100.0)


def test_scarce_green_spreads_across_customers():
    # Total green (60) < sum of targets (100). Both distributions "50/10" and
    # "30/30" tie on total RE shortfall, but the maximin fairness tie-break
    # spreads green proportionally so both customers reach the same RE ratio
    # instead of one hitting target while the other is starved.
    farms = [FarmSupply(1, 60.0, feed_in_price_per_kwh=4.0)]
    demands = [_demand(1, 100.0, 50.0), _demand(2, 100.0, 50.0)]
    out = optimize_scenario("2024-01", farms, demands, OPTS)
    ct = {c.customer_id: c for c in out.customer_targets}
    assert ct[1].allocated_mwh == pytest.approx(30.0, abs=1.0)
    assert ct[2].allocated_mwh == pytest.approx(30.0, abs=1.0)


def test_deterministic_shuffled_input():
    farms = [
        FarmSupply(1, 100.0, feed_in_price_per_kwh=4.0),
        FarmSupply(2, 80.0, feed_in_price_per_kwh=4.2),
        FarmSupply(3, 60.0, feed_in_price_per_kwh=3.8),
    ]
    demands = [
        _demand(1, 120.0, 50.0),
        _demand(2, 90.0, 70.0),
        _demand(3, 40.0, 100.0),
    ]
    a = optimize_scenario("2024-01", farms, demands, OPTS)
    b = optimize_scenario(
        "2024-01", list(reversed(farms)), list(reversed(demands)), OPTS
    )
    assert _alloc(a) == _alloc(b)
