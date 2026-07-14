"""Matching service: load period data, run the engine, persist the run."""

from __future__ import annotations

import calendar
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.matching import (
    ContractInput,
    CustomerDemand,
    FarmSupply,
    MatchingOutcome,
    match_period,
)
from app.models import (
    ConsumptionData,
    Contract,
    Customer,
    GenerationData,
    MatchingResult,
    MatchingRun,
    WindFarm,
)
from app.models.enums import MatchingRunStatus


def period_bounds(period: str) -> tuple[date, date]:
    """Return (first_day, last_day) for a 'YYYY-MM' period string."""
    year, month = int(period[:4]), int(period[5:7])
    last = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last)


def _sum_generation(db: Session, start: date, end: date) -> dict[int, float]:
    stmt = select(GenerationData).where(
        GenerationData.period_start >= start,
        GenerationData.period_start <= end,
    )
    totals: dict[int, float] = {}
    for row in db.execute(stmt).scalars():
        totals[row.wind_farm_id] = (
            totals.get(row.wind_farm_id, 0.0) + row.generated_energy_mwh
        )
    return totals


def _sum_consumption(db: Session, start: date, end: date) -> dict[int, float]:
    stmt = select(ConsumptionData).where(
        ConsumptionData.period_start >= start,
        ConsumptionData.period_start <= end,
    )
    totals: dict[int, float] = {}
    for row in db.execute(stmt).scalars():
        totals[row.customer_id] = (
            totals.get(row.customer_id, 0.0) + row.consumed_energy_mwh
        )
    return totals


def compute_outcome(db: Session, period: str) -> MatchingOutcome:
    """Run the engine for a period without persisting (used by analytics)."""
    start, end = period_bounds(period)
    gen = _sum_generation(db, start, end)
    con = _sum_consumption(db, start, end)

    farms = [
        FarmSupply(farm_id=f.id, generated_mwh=gen.get(f.id, 0.0))
        for f in db.execute(select(WindFarm).order_by(WindFarm.id)).scalars()
    ]
    demands = [
        CustomerDemand(customer_id=c.id, consumed_mwh=con.get(c.id, 0.0))
        for c in db.execute(select(Customer).order_by(Customer.id)).scalars()
    ]
    contracts = [
        ContractInput(
            contract_id=c.id,
            contract_number=c.contract_number,
            wind_farm_id=c.wind_farm_id,
            customer_id=c.customer_id,
            start_date=c.start_date,
            end_date=c.end_date,
            status=c.status.value,
            priority=c.priority,
            contracted_energy_mwh=c.contracted_energy_mwh,
            contracted_percentage=c.contracted_percentage,
        )
        for c in db.execute(select(Contract).order_by(Contract.id)).scalars()
    ]
    return match_period(period, start, end, farms, demands, contracts)


def _build_summaries(
    outcome: MatchingOutcome, targets: dict[int, float]
) -> tuple[dict, dict]:
    customers = outcome.customer_summaries
    input_summary = {
        "wind_farms": len(outcome.farm_summaries),
        "customers": len(customers),
        "contracts_considered": len(outcome.allocations) + len(outcome.skipped),
        "contracts_allocated": sum(
            1 for a in outcome.allocations if a.allocated_mwh > 0
        ),
        "contracts_skipped": len(outcome.skipped),
    }
    met = 0
    customer_rows = []
    for c in customers:
        target_pct = targets.get(c.customer_id, 0.0)
        target_energy = round(c.consumption_mwh * target_pct / 100.0, 6)
        gap = round(max(0.0, target_energy - c.allocated_mwh), 6)
        target_met = c.allocated_mwh + 1e-9 >= target_energy and target_energy > 0
        if target_met:
            met += 1
        customer_rows.append(
            {
                "customer_id": c.customer_id,
                "consumption_mwh": c.consumption_mwh,
                "allocated_mwh": c.allocated_mwh,
                "achieved_re_percent": c.achieved_re_percent,
                "re_target_percent": target_pct,
                "gap_to_target_mwh": gap,
                "target_met": target_met,
            }
        )
    avg_re = (
        round(sum(c.achieved_re_percent for c in customers) / len(customers), 6)
        if customers
        else 0.0
    )
    result_summary = {
        "total_generation_mwh": outcome.total_generated_mwh,
        "total_allocated_mwh": outcome.total_allocated_mwh,
        "total_unallocated_mwh": outcome.total_unallocated_mwh,
        "average_re_percent": avg_re,
        "customers_meeting_target": met,
        "customers": customer_rows,
        "wind_farms": [
            {
                "wind_farm_id": f.farm_id,
                "generated_mwh": f.generated_mwh,
                "allocated_mwh": f.allocated_mwh,
                "unallocated_mwh": f.unallocated_mwh,
            }
            for f in outcome.farm_summaries
        ],
        "skipped_contracts": [
            {"contract_id": s.contract_id, "reason": s.reason} for s in outcome.skipped
        ],
    }
    return input_summary, result_summary


def run_matching(db: Session, period: str) -> MatchingRun:
    """Execute matching for a period and persist the run and its results."""
    run = MatchingRun(
        period=period,
        status=MatchingRunStatus.RUNNING,
        started_at=utcnow(),
    )
    db.add(run)
    db.flush()  # assign run.id

    outcome = compute_outcome(db, period)
    targets = {
        c.id: c.re_target_percent for c in db.execute(select(Customer)).scalars()
    }
    consumption_by_customer = {
        c.customer_id: c.consumption_mwh for c in outcome.customer_summaries
    }
    achieved_by_customer = {
        c.customer_id: c.achieved_re_percent for c in outcome.customer_summaries
    }

    for alloc in outcome.allocations:
        db.add(
            MatchingResult(
                matching_run_id=run.id,
                wind_farm_id=alloc.wind_farm_id,
                customer_id=alloc.customer_id,
                contract_id=alloc.contract_id,
                period=period,
                allocated_energy_mwh=alloc.allocated_mwh,
                customer_consumption_mwh=consumption_by_customer.get(
                    alloc.customer_id, 0.0
                ),
                achieved_re_percent=achieved_by_customer.get(alloc.customer_id, 0.0),
                allocation_reason=alloc.reason,
            )
        )

    input_summary, result_summary = _build_summaries(outcome, targets)
    run.input_summary = input_summary
    run.result_summary = result_summary
    run.status = MatchingRunStatus.COMPLETED
    run.completed_at = utcnow()

    db.commit()
    db.refresh(run)
    return run


def get_run(db: Session, run_id: int) -> MatchingRun | None:
    return db.get(MatchingRun, run_id)


def list_runs(db: Session, *, limit: int = 100, offset: int = 0) -> list[MatchingRun]:
    stmt = (
        select(MatchingRun).order_by(MatchingRun.id.desc()).offset(offset).limit(limit)
    )
    return list(db.execute(stmt).scalars().all())


def list_results(
    db: Session,
    *,
    run_id: int | None = None,
    period: str | None = None,
    limit: int = 500,
    offset: int = 0,
) -> list[MatchingResult]:
    stmt = select(MatchingResult)
    if run_id is not None:
        stmt = stmt.where(MatchingResult.matching_run_id == run_id)
    if period is not None:
        stmt = stmt.where(MatchingResult.period == period)
    stmt = stmt.order_by(MatchingResult.id).offset(offset).limit(limit)
    return list(db.execute(stmt).scalars().all())
