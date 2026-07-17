"""Unit tests for the joint per-time-slot MILP optimizer (P4b)."""

from __future__ import annotations

from datetime import date

import pytest

from app.matching.engine import ContractInput
from app.matching.slot_engine import SlotCustomerDemand, SlotFarmSupply
from app.matching.slot_optimizer import SlotOptimizeOptions, optimize_slots
from app.models.enums import TimeSlot

START = date(2024, 1, 1)  # January -> non-summer
END = date(2024, 1, 31)
OPTS = SlotOptimizeOptions(default_feed_in_price_per_kwh=4.0)


def _contract(cid, num, farm, cust, price=4.8, energy=None, pct=None, priority=100):
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


def _supply(farm, **per_slot):
    return [SlotFarmSupply(farm, s, mwh) for s, mwh in per_slot.items()]


def _demand(cust, target, **per_slot):
    return [
        SlotCustomerDemand(
            cust, s, mwh, green_target_type="re_percent", re_target_percent=target
        )
        for s, mwh in per_slot.items()
    ]


def _cust_total(out, cid):
    return {c.customer_id: c for c in out.customer_totals}[cid]


def test_eq5_per_slot_caps():
    farms = _supply(
        1, **{TimeSlot.PEAK: 5.0, TimeSlot.HALF_PEAK: 5.0, TimeSlot.OFF_PEAK: 5.0}
    )
    demands = _demand(
        1,
        100.0,
        **{TimeSlot.PEAK: 100.0, TimeSlot.HALF_PEAK: 100.0, TimeSlot.OFF_PEAK: 100.0},
    )
    out = optimize_slots(
        "2024-01",
        START,
        END,
        farms,
        demands,
        [_contract(1, "C1", 1, 1, pct=100.0)],
        OPTS,
    )
    for a in out.allocations:
        assert a.allocated_mwh <= 5.0 + 1e-6  # cannot exceed that slot's generation


def test_eq7_minimizes_allocation_to_target():
    # supply is ample; RE target 50% -> allocate exactly 50% of consumption (no more)
    farms = _supply(
        1, **{TimeSlot.PEAK: 100.0, TimeSlot.HALF_PEAK: 100.0, TimeSlot.OFF_PEAK: 100.0}
    )
    demands = _demand(
        1,
        50.0,
        **{TimeSlot.PEAK: 40.0, TimeSlot.HALF_PEAK: 30.0, TimeSlot.OFF_PEAK: 30.0},
    )
    out = optimize_slots(
        "2024-01",
        START,
        END,
        farms,
        demands,
        [_contract(1, "C1", 1, 1, pct=100.0)],
        OPTS,
    )
    ct = _cust_total(out, 1)
    assert ct.consumption_mwh == 100.0
    assert ct.allocated_mwh == pytest.approx(
        50.0, abs=1e-2
    )  # exactly the target, not more
    assert ct.re_percent == pytest.approx(50.0, abs=1e-2)


def test_re_infeasible_offpeak_surplus_shortfall():
    # wind generates only off-peak, customer uses only peak -> can't match -> shortfall
    farms = _supply(
        1, **{TimeSlot.PEAK: 0.0, TimeSlot.HALF_PEAK: 0.0, TimeSlot.OFF_PEAK: 100.0}
    )
    demands = _demand(
        1,
        100.0,
        **{TimeSlot.PEAK: 80.0, TimeSlot.HALF_PEAK: 20.0, TimeSlot.OFF_PEAK: 0.0},
    )
    out = optimize_slots(
        "2024-01",
        START,
        END,
        farms,
        demands,
        [_contract(1, "C1", 1, 1, pct=100.0)],
        OPTS,
    )
    ct = _cust_total(out, 1)
    assert ct.allocated_mwh == pytest.approx(
        0.0, abs=1e-2
    )  # off-peak green can't land in peak/half demand
    assert ct.re_shortfall_mwh > 0
    for cs in out.customer_slot:
        assert cs.re_percent <= 100.0 + 1e-6


def test_secondary_matching_redistributes_same_slot_surplus():
    # one farm, peak slot: cust1 uses 20, cust2 uses 60, farm peak gen 100.
    # global optimisation serves both from the shared same-slot pool.
    farms = _supply(
        1, **{TimeSlot.PEAK: 100.0, TimeSlot.HALF_PEAK: 0.0, TimeSlot.OFF_PEAK: 0.0}
    )
    demands = _demand(
        1,
        100.0,
        **{TimeSlot.PEAK: 20.0, TimeSlot.HALF_PEAK: 0.0, TimeSlot.OFF_PEAK: 0.0},
    ) + _demand(
        2,
        100.0,
        **{TimeSlot.PEAK: 60.0, TimeSlot.HALF_PEAK: 0.0, TimeSlot.OFF_PEAK: 0.0},
    )
    contracts = [
        _contract(1, "C1", 1, 1, pct=100.0),
        _contract(2, "C2", 1, 2, pct=100.0),
    ]
    out = optimize_slots("2024-01", START, END, farms, demands, contracts, OPTS)
    # both fully served from the shared peak pool (20 + 60 = 80 <= 100)
    assert _cust_total(out, 1).allocated_mwh == pytest.approx(20.0, abs=1e-2)
    assert _cust_total(out, 2).allocated_mwh == pytest.approx(60.0, abs=1e-2)


def test_deterministic_shuffled():
    farms = _supply(
        1, **{TimeSlot.PEAK: 40.0, TimeSlot.HALF_PEAK: 30.0, TimeSlot.OFF_PEAK: 60.0}
    )
    demands = _demand(
        1,
        80.0,
        **{TimeSlot.PEAK: 30.0, TimeSlot.HALF_PEAK: 40.0, TimeSlot.OFF_PEAK: 50.0},
    )
    contracts = [_contract(1, "C1", 1, 1, pct=100.0)]
    a = optimize_slots("2024-01", START, END, farms, demands, contracts, OPTS)
    b = optimize_slots(
        "2024-01",
        START,
        END,
        list(reversed(farms)),
        list(reversed(demands)),
        contracts,
        OPTS,
    )
    ma = {(x.contract_id, x.slot): x.allocated_mwh for x in a.allocations}
    mb = {(x.contract_id, x.slot): x.allocated_mwh for x in b.allocations}
    assert ma == mb


def test_empty_no_crash():
    out = optimize_slots("2024-01", START, END, [], [], [], OPTS)
    assert out.allocations == []
    assert out.customer_totals == []
