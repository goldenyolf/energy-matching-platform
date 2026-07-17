"""Per-time-slot greedy green-energy matcher (pure, deterministic).

Runs the same greedy min(farm, customer, cap) allocation as the monthly engine,
but per Taipower time slot (peak / half-peak / off-peak) within a month. A
contract's percentage cap applies per slot (patent eq.3); its monthly energy cap
is a budget shared across slots (peak first). RE aggregates across slots
(patent eq.6). The monthly engine is untouched; helpers are reused from engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from app.matching.engine import (
    _EPS,
    ContractInput,
    CustomerSummary,
    FarmSummary,
    SkippedContract,
    _is_eligible,
    build_customer_summary,
    build_farm_summary,
)
from app.matching.tou import SLOT_ORDER, season_of
from app.models.enums import Season, TimeSlot


@dataclass(frozen=True)
class SlotFarmSupply:
    farm_id: int
    slot: TimeSlot
    generated_mwh: float


@dataclass(frozen=True)
class SlotCustomerDemand:
    customer_id: int
    slot: TimeSlot
    consumed_mwh: float
    green_target_type: str | None = None
    re_target_percent: float | None = None
    target_energy_mwh: float | None = None


@dataclass
class SlotAllocation:
    contract_id: int
    contract_number: str
    wind_farm_id: int
    customer_id: int
    slot: TimeSlot
    allocated_mwh: float
    reason: str


@dataclass
class SlotSubtotal:
    slot: TimeSlot
    customer_summaries: list[CustomerSummary]
    farm_summaries: list[FarmSummary]


@dataclass
class SlotMatchingOutcome:
    period: str
    season: Season
    allocations: list[SlotAllocation] = field(default_factory=list)
    skipped: list[SkippedContract] = field(default_factory=list)
    customer_summaries: list[CustomerSummary] = field(default_factory=list)
    farm_summaries: list[FarmSummary] = field(default_factory=list)
    slot_subtotals: list[SlotSubtotal] = field(default_factory=list)


def _slot_reason(
    alloc: float,
    farm_rem: float,
    cust_rem: float,
    pct_cap: float,
    energy_cap: float,
) -> str:
    if alloc <= _EPS:
        if farm_rem <= _EPS:
            return "no allocation: farm slot generation exhausted"
        if cust_rem <= _EPS:
            return "no allocation: customer slot demand met"
        if pct_cap <= _EPS:
            return "no allocation: contract percentage cap is zero"
        if energy_cap <= _EPS:
            return "no allocation: contract monthly energy budget exhausted"
        return "no allocation"
    binding: list[str] = []
    if abs(alloc - farm_rem) <= _EPS:
        binding.append("farm slot supply")
    if abs(alloc - cust_rem) <= _EPS:
        binding.append("customer slot demand")
    if pct_cap != float("inf") and abs(alloc - pct_cap) <= _EPS:
        binding.append("contract percentage cap")
    if energy_cap != float("inf") and abs(alloc - energy_cap) <= _EPS:
        binding.append("contract monthly energy budget")
    where = ", ".join(binding) if binding else "available supply"
    return f"allocated {round(alloc, 3)} MWh (limited by {where})"


def match_slots(
    period: str,
    period_start: date,
    period_end: date,
    farms: list[SlotFarmSupply],
    demands: list[SlotCustomerDemand],
    contracts: list[ContractInput],
) -> SlotMatchingOutcome:
    season = season_of(period_start.month)
    outcome = SlotMatchingOutcome(period=period, season=season)

    gen: dict[tuple[int, TimeSlot], float] = {}
    for f in farms:
        gen[(f.farm_id, f.slot)] = gen.get((f.farm_id, f.slot), 0.0) + f.generated_mwh
    con: dict[tuple[int, TimeSlot], float] = {}
    for d in demands:
        con[(d.customer_id, d.slot)] = (
            con.get((d.customer_id, d.slot), 0.0) + d.consumed_mwh
        )

    farm_ids = sorted({f.farm_id for f in farms})
    cust_ids = sorted({d.customer_id for d in demands})

    remaining_gen = dict(gen)
    alloc_cust_slot: dict[tuple[int, TimeSlot], float] = {}
    remaining_energy: dict[int, float] = {}

    ordered = sorted(
        contracts, key=lambda c: (c.priority, c.start_date, c.contract_number)
    )
    eligible: list[ContractInput] = []
    for c in ordered:
        skip = _is_eligible(c, period_start, period_end)
        if skip is not None:
            outcome.skipped.append(
                SkippedContract(c.contract_id, c.contract_number, skip)
            )
            continue
        eligible.append(c)
        if c.contracted_energy_mwh is not None:
            remaining_energy[c.contract_id] = c.contracted_energy_mwh

    INF = float("inf")
    for slot in SLOT_ORDER:
        for c in eligible:
            farm_gen_slot = gen.get((c.wind_farm_id, slot), 0.0)
            farm_rem = remaining_gen.get((c.wind_farm_id, slot), 0.0)
            cust_rem = con.get((c.customer_id, slot), 0.0) - alloc_cust_slot.get(
                (c.customer_id, slot), 0.0
            )
            pct_cap = (
                c.contracted_percentage / 100.0 * farm_gen_slot
                if c.contracted_percentage is not None
                else INF
            )
            energy_cap = remaining_energy.get(c.contract_id, INF)

            candidates = [max(0.0, farm_rem), max(0.0, cust_rem)]
            if pct_cap != INF:
                candidates.append(max(0.0, pct_cap))
            if energy_cap != INF:
                candidates.append(max(0.0, energy_cap))
            alloc = round(min(candidates), 6)

            outcome.allocations.append(
                SlotAllocation(
                    contract_id=c.contract_id,
                    contract_number=c.contract_number,
                    wind_farm_id=c.wind_farm_id,
                    customer_id=c.customer_id,
                    slot=slot,
                    allocated_mwh=alloc,
                    reason=_slot_reason(alloc, farm_rem, cust_rem, pct_cap, energy_cap),
                )
            )
            if alloc > 0:
                remaining_gen[(c.wind_farm_id, slot)] = farm_rem - alloc
                alloc_cust_slot[(c.customer_id, slot)] = (
                    alloc_cust_slot.get((c.customer_id, slot), 0.0) + alloc
                )
                if c.contract_id in remaining_energy:
                    remaining_energy[c.contract_id] -= alloc

    for slot in SLOT_ORDER:
        cs = [
            build_customer_summary(
                cid,
                con.get((cid, slot), 0.0),
                alloc_cust_slot.get((cid, slot), 0.0),
            )
            for cid in cust_ids
        ]
        fs = [
            build_farm_summary(
                fid,
                gen.get((fid, slot), 0.0),
                gen.get((fid, slot), 0.0) - remaining_gen.get((fid, slot), 0.0),
            )
            for fid in farm_ids
        ]
        outcome.slot_subtotals.append(SlotSubtotal(slot, cs, fs))

    for cid in cust_ids:
        consumed = sum(con.get((cid, s), 0.0) for s in SLOT_ORDER)
        allocated = sum(alloc_cust_slot.get((cid, s), 0.0) for s in SLOT_ORDER)
        outcome.customer_summaries.append(
            build_customer_summary(cid, consumed, allocated)
        )
    for fid in farm_ids:
        generated = sum(gen.get((fid, s), 0.0) for s in SLOT_ORDER)
        allocated = sum(
            gen.get((fid, s), 0.0) - remaining_gen.get((fid, s), 0.0)
            for s in SLOT_ORDER
        )
        outcome.farm_summaries.append(build_farm_summary(fid, generated, allocated))

    return outcome
