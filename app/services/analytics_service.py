"""Analytics computed on-the-fly from current data via the matching engine."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Contract, Customer, WindFarm
from app.schemas.analytics import (
    ContractUtilization,
    CustomerAnalytics,
    PeriodSummary,
    WindFarmAnalytics,
)
from app.services.matching_service import compute_outcome


def customer_analytics(db: Session, period: str) -> list[CustomerAnalytics]:
    outcome = compute_outcome(db, period)
    customers = {c.id: c for c in db.execute(select(Customer)).scalars()}
    rows: list[CustomerAnalytics] = []
    for s in outcome.customer_summaries:
        c = customers[s.customer_id]
        target_energy = round(s.consumption_mwh * c.re_target_percent / 100.0, 6)
        gap = round(max(0.0, target_energy - s.allocated_mwh), 6)
        rows.append(
            CustomerAnalytics(
                customer_id=c.id,
                code=c.code,
                company_name=c.company_name,
                period=period,
                consumption_mwh=s.consumption_mwh,
                allocated_mwh=s.allocated_mwh,
                achieved_re_percent=s.achieved_re_percent,
                re_target_percent=c.re_target_percent,
                target_energy_mwh=target_energy,
                gap_to_target_mwh=gap,
                target_met=(target_energy > 0 and gap <= 1e-9),
            )
        )
    return rows


def wind_farm_analytics(db: Session, period: str) -> list[WindFarmAnalytics]:
    outcome = compute_outcome(db, period)
    farms = {f.id: f for f in db.execute(select(WindFarm)).scalars()}
    rows: list[WindFarmAnalytics] = []
    for s in outcome.farm_summaries:
        f = farms[s.farm_id]
        util = (
            round(s.allocated_mwh / s.generated_mwh * 100.0, 6)
            if s.generated_mwh > 0
            else 0.0
        )
        rows.append(
            WindFarmAnalytics(
                wind_farm_id=f.id,
                code=f.code,
                name=f.name,
                period=period,
                generated_mwh=s.generated_mwh,
                allocated_mwh=s.allocated_mwh,
                unallocated_mwh=s.unallocated_mwh,
                utilization_percent=util,
            )
        )
    return rows


def contract_utilization(db: Session, period: str) -> list[ContractUtilization]:
    outcome = compute_outcome(db, period)
    numbers = {c.id: c.contract_number for c in db.execute(select(Contract)).scalars()}
    rows: list[ContractUtilization] = []
    for a in outcome.allocations:
        limit = a.contract_limit_mwh
        util = (
            round(a.allocated_mwh / limit * 100.0, 6) if limit and limit > 0 else None
        )
        rows.append(
            ContractUtilization(
                contract_id=a.contract_id,
                contract_number=numbers.get(a.contract_id, a.contract_number),
                period=period,
                contract_limit_mwh=limit,
                allocated_mwh=a.allocated_mwh,
                utilization_percent=util,
            )
        )
    return rows


def period_summary(db: Session, period: str) -> PeriodSummary:
    outcome = compute_outcome(db, period)
    customers = customer_analytics(db, period)
    total_consumption = round(sum(c.consumption_mwh for c in customers), 6)
    avg_re = (
        round(sum(c.achieved_re_percent for c in customers) / len(customers), 6)
        if customers
        else 0.0
    )
    met = sum(1 for c in customers if c.target_met)
    return PeriodSummary(
        period=period,
        total_generation_mwh=outcome.total_generated_mwh,
        total_allocated_mwh=outcome.total_allocated_mwh,
        total_unallocated_mwh=outcome.total_unallocated_mwh,
        total_consumption_mwh=total_consumption,
        average_re_percent=avg_re,
        customer_count=len(customers),
        wind_farm_count=len(outcome.farm_summaries),
        customers_meeting_target=met,
    )
