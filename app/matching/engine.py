"""Deterministic monthly green-energy matching engine.

The engine is a **pure function** over plain dataclasses — it performs no I/O and
holds no global state, so the same input always yields the same output. See
``docs/matching-rules.md`` for the full specification.

Allocation rules (per period, one calendar month)
--------------------------------------------------
1. Only contracts that are ``active`` **and** valid during the period participate.
2. A wind farm's generated energy is a finite pool; it is never allocated twice.
3. A customer never receives more green energy than it consumed that month.
4. A contract never allocates more than its cap (fixed volume and/or a share of
   the farm's generation — the tighter of the two).
5. Contracts are served by ascending ``priority`` (lower = higher priority), then
   by ``start_date``, then ``contract_number`` — a total, stable ordering.
6. Every allocation records the binding constraint as a human-readable reason.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

# Floating-point tolerance for "is this the binding constraint" comparisons.
_EPS = 1e-9


@dataclass(frozen=True)
class FarmSupply:
    farm_id: int
    generated_mwh: float


@dataclass(frozen=True)
class CustomerDemand:
    customer_id: int
    consumed_mwh: float


@dataclass(frozen=True)
class ContractInput:
    contract_id: int
    contract_number: str
    wind_farm_id: int
    customer_id: int
    start_date: date
    end_date: date
    status: str
    priority: int = 100
    contracted_energy_mwh: float | None = None
    contracted_percentage: float | None = None


@dataclass
class Allocation:
    contract_id: int
    contract_number: str
    wind_farm_id: int
    customer_id: int
    allocated_mwh: float
    contract_limit_mwh: float | None
    reason: str


@dataclass
class SkippedContract:
    contract_id: int
    contract_number: str
    reason: str


@dataclass
class CustomerSummary:
    customer_id: int
    consumption_mwh: float
    allocated_mwh: float
    achieved_re_percent: float


@dataclass
class FarmSummary:
    farm_id: int
    generated_mwh: float
    allocated_mwh: float
    unallocated_mwh: float


@dataclass
class MatchingOutcome:
    period: str
    allocations: list[Allocation] = field(default_factory=list)
    skipped: list[SkippedContract] = field(default_factory=list)
    customer_summaries: list[CustomerSummary] = field(default_factory=list)
    farm_summaries: list[FarmSummary] = field(default_factory=list)

    @property
    def total_generated_mwh(self) -> float:
        return round(sum(f.generated_mwh for f in self.farm_summaries), 6)

    @property
    def total_allocated_mwh(self) -> float:
        return round(sum(f.allocated_mwh for f in self.farm_summaries), 6)

    @property
    def total_unallocated_mwh(self) -> float:
        return round(sum(f.unallocated_mwh for f in self.farm_summaries), 6)


def _is_eligible(
    contract: ContractInput, period_start: date, period_end: date
) -> str | None:
    """Return a skip reason if the contract cannot participate, else ``None``."""
    if contract.status != "active":
        return f"contract status is '{contract.status}', not active"
    if contract.start_date > period_end:
        return "contract has not started yet for this period"
    if contract.end_date < period_start:
        return "contract already ended before this period"
    return None


def _contract_limit(contract: ContractInput, farm_generation: float) -> float | None:
    """The contract's monthly allocation cap (``None`` = uncapped)."""
    limits: list[float] = []
    if contract.contracted_energy_mwh is not None:
        limits.append(contract.contracted_energy_mwh)
    if contract.contracted_percentage is not None:
        limits.append(contract.contracted_percentage / 100.0 * farm_generation)
    return min(limits) if limits else None


def _reason(
    allocation: float,
    farm_remaining: float,
    customer_remaining: float,
    contract_limit: float | None,
) -> str:
    if allocation <= _EPS:
        if farm_remaining <= _EPS:
            return "no allocation: wind farm has no remaining generation"
        if customer_remaining <= _EPS:
            return "no allocation: customer consumption already fully covered"
        if contract_limit is not None and contract_limit <= _EPS:
            return "no allocation: contract cap is zero"
        return "no allocation"
    binding: list[str] = []
    if abs(allocation - farm_remaining) <= _EPS:
        binding.append("wind farm supply")
    if abs(allocation - customer_remaining) <= _EPS:
        binding.append("customer demand")
    if contract_limit is not None and abs(allocation - contract_limit) <= _EPS:
        binding.append("contract cap")
    where = ", ".join(binding) if binding else "available supply"
    return f"allocated {round(allocation, 3)} MWh (limited by {where})"


def match_period(
    period: str,
    period_start: date,
    period_end: date,
    farms: list[FarmSupply],
    demands: list[CustomerDemand],
    contracts: list[ContractInput],
) -> MatchingOutcome:
    """Run the monthly matching algorithm and return a full, auditable outcome."""
    generation = {f.farm_id: f.generated_mwh for f in farms}
    remaining_generation = dict(generation)
    consumption = {d.customer_id: d.consumed_mwh for d in demands}
    allocated_to_customer: dict[int, float] = {d.customer_id: 0.0 for d in demands}
    allocated_to_farm: dict[int, float] = {f.farm_id: 0.0 for f in farms}

    outcome = MatchingOutcome(period=period)

    ordered = sorted(
        contracts,
        key=lambda c: (c.priority, c.start_date, c.contract_number),
    )

    for contract in ordered:
        skip = _is_eligible(contract, period_start, period_end)
        if skip is not None:
            outcome.skipped.append(
                SkippedContract(contract.contract_id, contract.contract_number, skip)
            )
            continue

        farm_gen = generation.get(contract.wind_farm_id, 0.0)
        farm_remaining = remaining_generation.get(contract.wind_farm_id, 0.0)
        customer_remaining = consumption.get(
            contract.customer_id, 0.0
        ) - allocated_to_customer.get(contract.customer_id, 0.0)
        limit = _contract_limit(contract, farm_gen)

        candidates = [max(0.0, farm_remaining), max(0.0, customer_remaining)]
        if limit is not None:
            candidates.append(max(0.0, limit))
        allocation = round(min(candidates), 6)

        reason = _reason(allocation, farm_remaining, customer_remaining, limit)
        outcome.allocations.append(
            Allocation(
                contract_id=contract.contract_id,
                contract_number=contract.contract_number,
                wind_farm_id=contract.wind_farm_id,
                customer_id=contract.customer_id,
                allocated_mwh=allocation,
                contract_limit_mwh=(None if limit is None else round(limit, 6)),
                reason=reason,
            )
        )

        if allocation > 0:
            remaining_generation[contract.wind_farm_id] = farm_remaining - allocation
            allocated_to_customer[contract.customer_id] = (
                allocated_to_customer.get(contract.customer_id, 0.0) + allocation
            )
            allocated_to_farm[contract.wind_farm_id] = (
                allocated_to_farm.get(contract.wind_farm_id, 0.0) + allocation
            )

    for d in demands:
        allocated = round(allocated_to_customer.get(d.customer_id, 0.0), 6)
        achieved = (
            round(allocated / d.consumed_mwh * 100.0, 6) if d.consumed_mwh > 0 else 0.0
        )
        outcome.customer_summaries.append(
            CustomerSummary(d.customer_id, d.consumed_mwh, allocated, achieved)
        )

    for f in farms:
        allocated = round(allocated_to_farm.get(f.farm_id, 0.0), 6)
        outcome.farm_summaries.append(
            FarmSummary(
                farm_id=f.farm_id,
                generated_mwh=f.generated_mwh,
                allocated_mwh=allocated,
                unallocated_mwh=round(f.generated_mwh - allocated, 6),
            )
        )

    return outcome
