"""Unit tests for the per-time-slot greedy matcher."""

from __future__ import annotations

from datetime import date

from app.matching.engine import ContractInput
from app.matching.slot_engine import (
    SlotCustomerDemand,
    SlotFarmSupply,
    match_slots,
)
from app.models.enums import Season, TimeSlot

START = date(2024, 1, 1)  # January -> NON_SUMMER
END = date(2024, 1, 31)


def _contract(cid, num, farm, cust, energy=None, pct=None, priority=100):
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
        price_per_kwh=4.5,
    )


def _supply(farm, **per_slot):
    return [SlotFarmSupply(farm, s, mwh) for s, mwh in per_slot.items()]


def _demand(cust, **per_slot):
    return [SlotCustomerDemand(cust, s, mwh) for s, mwh in per_slot.items()]


def _amap(outcome):
    return {(a.contract_id, a.slot): a.allocated_mwh for a in outcome.allocations}


def test_per_slot_min_allocation():
    farms = _supply(
        1, **{TimeSlot.PEAK: 40.0, TimeSlot.HALF_PEAK: 30.0, TimeSlot.OFF_PEAK: 20.0}
    )
    demands = _demand(
        1, **{TimeSlot.PEAK: 25.0, TimeSlot.HALF_PEAK: 50.0, TimeSlot.OFF_PEAK: 10.0}
    )
    contracts = [_contract(1, "C1", 1, 1, pct=100.0)]
    out = match_slots("2024-01", START, END, farms, demands, contracts)
    a = _amap(out)
    assert a[(1, TimeSlot.PEAK)] == 25.0  # limited by demand
    assert a[(1, TimeSlot.HALF_PEAK)] == 30.0  # limited by farm supply
    assert a[(1, TimeSlot.OFF_PEAK)] == 10.0  # limited by demand
    assert out.season == Season.NON_SUMMER


def test_eq5_transfer_not_exceed_slot_generation():
    farms = _supply(
        1, **{TimeSlot.PEAK: 5.0, TimeSlot.HALF_PEAK: 5.0, TimeSlot.OFF_PEAK: 5.0}
    )
    demands = _demand(
        1, **{TimeSlot.PEAK: 100.0, TimeSlot.HALF_PEAK: 100.0, TimeSlot.OFF_PEAK: 100.0}
    )
    contracts = [_contract(1, "C1", 1, 1, pct=100.0)]
    out = match_slots("2024-01", START, END, farms, demands, contracts)
    for a in out.allocations:
        assert a.allocated_mwh <= 5.0 + 1e-9


def test_monthly_energy_budget_shared_across_slots_peak_first():
    # contract monthly energy cap 30; peak slot consumes it first
    farms = _supply(
        1, **{TimeSlot.PEAK: 100.0, TimeSlot.HALF_PEAK: 100.0, TimeSlot.OFF_PEAK: 100.0}
    )
    demands = _demand(
        1, **{TimeSlot.PEAK: 100.0, TimeSlot.HALF_PEAK: 100.0, TimeSlot.OFF_PEAK: 100.0}
    )
    contracts = [_contract(1, "C1", 1, 1, energy=30.0)]
    out = match_slots("2024-01", START, END, farms, demands, contracts)
    a = _amap(out)
    assert a[(1, TimeSlot.PEAK)] == 30.0
    assert a[(1, TimeSlot.HALF_PEAK)] == 0.0
    assert a[(1, TimeSlot.OFF_PEAK)] == 0.0
    total = sum(x.allocated_mwh for x in out.allocations)
    assert total == 30.0


def test_percentage_cap_per_slot():
    farms = _supply(
        1, **{TimeSlot.PEAK: 100.0, TimeSlot.HALF_PEAK: 100.0, TimeSlot.OFF_PEAK: 100.0}
    )
    demands = _demand(
        1, **{TimeSlot.PEAK: 100.0, TimeSlot.HALF_PEAK: 100.0, TimeSlot.OFF_PEAK: 100.0}
    )
    contracts = [_contract(1, "C1", 1, 1, pct=40.0)]
    out = match_slots("2024-01", START, END, farms, demands, contracts)
    for a in out.allocations:
        assert a.allocated_mwh == 40.0  # 40% of each slot's 100


def test_cross_slot_re_aggregation():
    farms = _supply(
        1, **{TimeSlot.PEAK: 50.0, TimeSlot.HALF_PEAK: 50.0, TimeSlot.OFF_PEAK: 50.0}
    )
    demands = _demand(
        1, **{TimeSlot.PEAK: 100.0, TimeSlot.HALF_PEAK: 100.0, TimeSlot.OFF_PEAK: 100.0}
    )
    contracts = [_contract(1, "C1", 1, 1, pct=100.0)]
    out = match_slots("2024-01", START, END, farms, demands, contracts)
    cs = {c.customer_id: c for c in out.customer_summaries}[1]
    assert cs.consumption_mwh == 300.0
    assert cs.allocated_mwh == 150.0
    assert cs.achieved_re_percent == 50.0


def test_deterministic_shuffled_inputs():
    farms = _supply(
        1, **{TimeSlot.PEAK: 40.0, TimeSlot.HALF_PEAK: 30.0, TimeSlot.OFF_PEAK: 60.0}
    ) + _supply(
        2, **{TimeSlot.PEAK: 20.0, TimeSlot.HALF_PEAK: 25.0, TimeSlot.OFF_PEAK: 15.0}
    )
    demands = _demand(
        1, **{TimeSlot.PEAK: 30.0, TimeSlot.HALF_PEAK: 40.0, TimeSlot.OFF_PEAK: 50.0}
    ) + _demand(
        2, **{TimeSlot.PEAK: 20.0, TimeSlot.HALF_PEAK: 20.0, TimeSlot.OFF_PEAK: 20.0}
    )
    contracts = [
        _contract(1, "C1", 1, 1, pct=80.0, priority=1),
        _contract(2, "C2", 2, 1, pct=100.0, priority=2),
        _contract(3, "C3", 2, 2, pct=100.0, priority=3),
    ]
    a = match_slots("2024-01", START, END, farms, demands, contracts)
    b = match_slots(
        "2024-01",
        START,
        END,
        list(reversed(farms)),
        list(reversed(demands)),
        list(reversed(contracts)),
    )
    assert _amap(a) == _amap(b)


def test_ineligible_skipped_and_empty_no_crash():
    farms = _supply(1, **{TimeSlot.PEAK: 10.0})
    demands = _demand(1, **{TimeSlot.PEAK: 10.0})
    expired = ContractInput(
        contract_id=9,
        contract_number="X",
        wind_farm_id=1,
        customer_id=1,
        start_date=START,
        end_date=END,
        status="expired",
        price_per_kwh=4.5,
    )
    out = match_slots("2024-01", START, END, farms, demands, [expired])
    assert out.allocations == []
    assert len(out.skipped) == 1
    empty = match_slots("2024-01", START, END, [], [], [])
    assert empty.allocations == []
    assert empty.customer_summaries == []
