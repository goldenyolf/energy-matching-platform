"""Unit tests for the pure matching engine."""

from __future__ import annotations

from datetime import date

import pytest

from app.matching import (
    ContractInput,
    CustomerDemand,
    FarmSupply,
    match_period,
)

PERIOD = "2024-01"
START, END = date(2024, 1, 1), date(2024, 1, 31)


def contract(
    cid,
    farm,
    cust,
    *,
    priority=100,
    energy=None,
    pct=None,
    status="active",
    start=date(2023, 1, 1),
    end=date(2030, 1, 1),
):
    return ContractInput(
        contract_id=cid,
        contract_number=f"C{cid}",
        wind_farm_id=farm,
        customer_id=cust,
        start_date=start,
        end_date=end,
        status=status,
        priority=priority,
        contracted_energy_mwh=energy,
        contracted_percentage=pct,
    )


def run(farms, demands, contracts):
    return match_period(PERIOD, START, END, farms, demands, contracts)


# --- ratio & volume caps ----------------------------------------------------


def test_ratio_contract_allocates_share_of_generation():
    out = run(
        [FarmSupply(1, 1000)],
        [CustomerDemand(1, 1000)],
        [contract(1, 1, 1, pct=40)],
    )
    assert out.allocations[0].allocated_mwh == pytest.approx(400)
    assert out.allocations[0].contract_limit_mwh == pytest.approx(400)


def test_volume_contract_allocates_fixed_energy():
    out = run(
        [FarmSupply(1, 1000)],
        [CustomerDemand(1, 1000)],
        [contract(1, 1, 1, energy=250)],
    )
    assert out.allocations[0].allocated_mwh == pytest.approx(250)


def test_both_caps_use_the_tighter_one():
    # pct=50 -> 500, energy=300 -> min is 300
    out = run(
        [FarmSupply(1, 1000)],
        [CustomerDemand(1, 1000)],
        [contract(1, 1, 1, pct=50, energy=300)],
    )
    assert out.allocations[0].allocated_mwh == pytest.approx(300)


# --- no over-allocation of generation --------------------------------------


def test_generation_is_never_over_allocated():
    out = run(
        [FarmSupply(1, 1000)],
        [CustomerDemand(1, 5000), CustomerDemand(2, 5000)],
        [
            contract(1, 1, 1, priority=1, energy=800),
            contract(2, 1, 2, priority=2, energy=800),
        ],
    )
    total = sum(a.allocated_mwh for a in out.allocations)
    assert total == pytest.approx(1000)
    farm = out.farm_summaries[0]
    assert farm.allocated_mwh == pytest.approx(1000)
    assert farm.unallocated_mwh == pytest.approx(0)


def test_surplus_generation_is_reported_as_unallocated():
    out = run(
        [FarmSupply(1, 1000)],
        [CustomerDemand(1, 300)],
        [contract(1, 1, 1, pct=100)],
    )
    assert out.allocations[0].allocated_mwh == pytest.approx(300)
    assert out.farm_summaries[0].unallocated_mwh == pytest.approx(700)


# --- no over-consumption ----------------------------------------------------


def test_customer_never_receives_more_than_consumption():
    out = run(
        [FarmSupply(1, 1000)],
        [CustomerDemand(1, 200)],
        [contract(1, 1, 1, energy=900)],
    )
    assert out.allocations[0].allocated_mwh == pytest.approx(200)
    assert "customer demand" in out.allocations[0].reason


# --- priority ordering ------------------------------------------------------


def test_lower_priority_number_is_served_first():
    out = run(
        [FarmSupply(1, 1000)],
        [CustomerDemand(1, 1000), CustomerDemand(2, 1000)],
        [
            contract(1, 1, 1, priority=5, energy=800),
            contract(2, 1, 2, priority=1, energy=800),
        ],
    )
    by_id = {a.contract_id: a for a in out.allocations}
    assert by_id[2].allocated_mwh == pytest.approx(800)  # priority 1 first
    assert by_id[1].allocated_mwh == pytest.approx(200)  # gets the remainder


def test_priority_ties_break_by_start_date_then_number():
    out = run(
        [FarmSupply(1, 1000)],
        [CustomerDemand(1, 1000), CustomerDemand(2, 1000)],
        [
            contract(1, 1, 1, priority=1, energy=700, start=date(2024, 1, 1)),
            contract(2, 1, 2, priority=1, energy=700, start=date(2023, 1, 1)),
        ],
    )
    by_id = {a.contract_id: a for a in out.allocations}
    # earlier start_date (contract 2) wins the tie
    assert by_id[2].allocated_mwh == pytest.approx(700)
    assert by_id[1].allocated_mwh == pytest.approx(300)


# --- contract validity period ----------------------------------------------


def test_future_contract_is_skipped():
    out = run(
        [FarmSupply(1, 1000)],
        [CustomerDemand(1, 1000)],
        [contract(1, 1, 1, energy=500, start=date(2025, 1, 1), end=date(2026, 1, 1))],
    )
    assert out.allocations == []
    assert out.skipped[0].contract_id == 1
    assert "not started" in out.skipped[0].reason


def test_ended_contract_is_skipped():
    out = run(
        [FarmSupply(1, 1000)],
        [CustomerDemand(1, 1000)],
        [contract(1, 1, 1, energy=500, start=date(2020, 1, 1), end=date(2023, 12, 31))],
    )
    assert out.allocations == []
    assert "ended" in out.skipped[0].reason


def test_non_active_status_is_skipped():
    out = run(
        [FarmSupply(1, 1000)],
        [CustomerDemand(1, 1000)],
        [contract(1, 1, 1, energy=500, status="expired")],
    )
    assert out.allocations == []
    assert "not active" in out.skipped[0].reason


def test_contract_valid_on_period_boundary_is_eligible():
    out = run(
        [FarmSupply(1, 1000)],
        [CustomerDemand(1, 1000)],
        [contract(1, 1, 1, energy=500, start=END, end=END)],  # exactly last day
    )
    assert out.allocations[0].allocated_mwh == pytest.approx(500)


# --- RE achievement calculation --------------------------------------------


def test_achieved_re_percent_is_allocated_over_consumption():
    out = run(
        [FarmSupply(1, 1000)],
        [CustomerDemand(1, 800)],
        [contract(1, 1, 1, energy=600)],
    )
    summary = out.customer_summaries[0]
    assert summary.allocated_mwh == pytest.approx(600)
    assert summary.achieved_re_percent == pytest.approx(75.0)


def test_achieved_re_is_zero_when_no_consumption():
    out = run(
        [FarmSupply(1, 1000)],
        [CustomerDemand(1, 0)],
        [contract(1, 1, 1, energy=500)],
    )
    assert out.customer_summaries[0].achieved_re_percent == 0.0


# --- determinism ------------------------------------------------------------


def test_engine_is_deterministic():
    farms = [FarmSupply(1, 1000), FarmSupply(2, 500)]
    demands = [CustomerDemand(1, 900), CustomerDemand(2, 400)]
    contracts = [
        contract(1, 1, 1, priority=2, pct=60),
        contract(2, 1, 2, priority=1, energy=300),
        contract(3, 2, 1, priority=1, pct=50),
    ]
    first = run(farms, demands, contracts)
    for _ in range(5):
        again = run(farms, demands, contracts)
        assert [a.allocated_mwh for a in again.allocations] == [
            a.allocated_mwh for a in first.allocations
        ]


def test_reason_reports_binding_constraint():
    out = run(
        [FarmSupply(1, 100)],
        [CustomerDemand(1, 1000)],
        [contract(1, 1, 1, pct=100)],
    )
    assert "wind farm supply" in out.allocations[0].reason


def test_optional_fields_default_none_and_ignored_by_engine():
    from datetime import date

    from app.matching.engine import (
        ContractInput,
        CustomerDemand,
        FarmSupply,
        match_period,
    )

    farms = [FarmSupply(farm_id=1, generated_mwh=100.0, feed_in_price_per_kwh=4.0)]
    demands = [
        CustomerDemand(
            customer_id=1,
            consumed_mwh=100.0,
            green_target_type="re_percent",
            re_target_percent=50.0,
            target_energy_mwh=None,
        )
    ]
    contracts = [
        ContractInput(
            contract_id=1,
            contract_number="C1",
            wind_farm_id=1,
            customer_id=1,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
            status="active",
            priority=100,
            contracted_energy_mwh=None,
            contracted_percentage=None,
            price_per_kwh=4.5,
        )
    ]
    out = match_period(
        "2024-01", date(2024, 1, 1), date(2024, 1, 31), farms, demands, contracts
    )
    # engine ignores the new fields; full allocation as before
    assert out.allocations[0].allocated_mwh == 100.0


def test_summary_helpers_match_inline_math():
    from app.matching.engine import build_customer_summary, build_farm_summary

    cs = build_customer_summary(1, 100.0, 55.5555555)
    # 55.5555555 is not exactly representable as a float (it is really
    # 55.55555549999...), so round(x, 6) correctly yields 55.555555.
    assert cs.allocated_mwh == 55.555555
    assert cs.achieved_re_percent == 55.555555
    cs0 = build_customer_summary(2, 0.0, 0.0)
    assert cs0.achieved_re_percent == 0.0
    fs = build_farm_summary(1, 100.0, 40.0)
    assert fs.unallocated_mwh == 60.0
