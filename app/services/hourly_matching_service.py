"""Hourly (24/7 CFE) matching service: model typical-day curves, match, score.

Compute-only (no persistence), mirroring the slot / optimize services. It shapes
each period total into a 24-hour typical-day profile (A9), runs the strict
time-coincident engine (B7), and reports the true CFE% alongside the "paper"
monthly-netting figure (the same totals matched with no timing constraint — the
upper bound the hourly score can never exceed).

All hourly curves are modeled (半模擬), not measured; real interval data (Roadmap
A4) replaces the profiles in place without touching the engine or the metric.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.matching import contract_terms
from app.matching.hourly_matching import (
    HourlyContract,
    HourlyCustomer,
    HourlyFarm,
    match_hourly,
)
from app.matching.hourly_profile import load_shape, to_hourly, wind_shape
from app.models import ConsumptionData, Contract, Customer, GenerationData, WindFarm
from app.schemas.hourly_matching import (
    HourlyCustomerOut,
    HourlyFarmOut,
    HourlyMatchingResult,
)
from app.services.matching_service import period_bounds

_MODELED_NOTE = (
    "逐時曲線為典型日型建模（風電夜強日弱、依產業別負載日型），Σ逐時＝原月量；"
    "接真實 interval 資料（A4）後原地替換。"
)


def _sum_by(rows, key_attr: str, val_attr: str) -> dict[int, float]:
    totals: dict[int, float] = {}
    for row in rows:
        key = getattr(row, key_attr)
        totals[key] = totals.get(key, 0.0) + getattr(row, val_attr)
    return totals


def compute_hourly_outcome(
    db: Session, period: str, customer_id: int | None = None
) -> HourlyMatchingResult:
    start, end = period_bounds(period)
    month = int(period[5:7])

    gen_totals = _sum_by(
        db.execute(
            select(GenerationData).where(
                GenerationData.period_start >= start,
                GenerationData.period_start <= end,
            )
        ).scalars(),
        "wind_farm_id",
        "generated_energy_mwh",
    )
    con_totals = _sum_by(
        db.execute(
            select(ConsumptionData).where(
                ConsumptionData.period_start >= start,
                ConsumptionData.period_start <= end,
            )
        ).scalars(),
        "customer_id",
        "consumed_energy_mwh",
    )

    wind = wind_shape()
    farm_rows = list(db.execute(select(WindFarm).order_by(WindFarm.id)).scalars())
    cust_rows = list(db.execute(select(Customer).order_by(Customer.id)).scalars())

    farms = [
        HourlyFarm(f.id, tuple(to_hourly(gen_totals.get(f.id, 0.0), wind)))
        for f in farm_rows
    ]
    customers = [
        HourlyCustomer(
            c.id, tuple(to_hourly(con_totals.get(c.id, 0.0), load_shape(c.industry)))
        )
        for c in cust_rows
    ]

    con_rows = list(db.execute(select(Contract).order_by(Contract.id)).scalars())
    eligible = [
        c
        for c in con_rows
        if c.status.value == "active" and c.start_date <= end and c.end_date >= start
    ]
    # Stable tie-break rank mirroring the monthly engine (start_date, number).
    order_rank = {
        c.id: i
        for i, c in enumerate(
            sorted(eligible, key=lambda k: (k.start_date, k.contract_number))
        )
    }

    def _hourly_contracts(shape: list[float]) -> list[HourlyContract]:
        out: list[HourlyContract] = []
        for c in eligible:
            cap = contract_terms.monthly_volume_cap(
                c.contracted_energy_mwh, c.monthly_shares, month
            )
            out.append(
                HourlyContract(
                    contract_id=c.id,
                    contract_number=c.contract_number,
                    wind_farm_id=c.wind_farm_id,
                    customer_id=c.customer_id,
                    priority=c.priority,
                    percentage=c.contracted_percentage,
                    hourly_cap=(
                        tuple(to_hourly(cap, shape)) if cap is not None else None
                    ),
                    order=order_rank[c.id],
                )
            )
        return out

    outcome = match_hourly(farms, customers, _hourly_contracts(wind))

    # "帳面" upper bound: match the same period totals in a single bucket (no
    # timing constraint) → monthly netting. cap collapses to the whole month.
    paper_farms = [HourlyFarm(f.id, (gen_totals.get(f.id, 0.0),)) for f in farm_rows]
    paper_customers = [
        HourlyCustomer(c.id, (con_totals.get(c.id, 0.0),)) for c in cust_rows
    ]
    paper = match_hourly(paper_farms, paper_customers, _hourly_contracts([1.0]))
    paper_by_customer = {c.customer_id: c.cfe_percent for c in paper.customers}

    farm_name = {f.id: f.name for f in farm_rows}
    cust_name = {c.id: c.company_name for c in cust_rows}
    cust_industry = {c.id: c.industry for c in cust_rows}

    customers_out = [
        HourlyCustomerOut(
            customer_id=c.customer_id,
            name=cust_name.get(c.customer_id, str(c.customer_id)),
            industry=cust_industry.get(c.customer_id),
            consumption_mwh=c.consumption_mwh,
            matched_mwh=c.matched_mwh,
            cfe_percent=c.cfe_percent,
            paper_re_percent=paper_by_customer.get(c.customer_id, 0.0),
            matched_by_hour=c.matched_by_hour,
            shortfall_by_hour=c.shortfall_by_hour,
        )
        for c in outcome.customers
    ]
    if customer_id is not None:
        customers_out = [c for c in customers_out if c.customer_id == customer_id]

    farms_out = [
        HourlyFarmOut(
            wind_farm_id=f.farm_id,
            name=farm_name.get(f.farm_id, str(f.farm_id)),
            generated_mwh=f.generated_mwh,
            matched_mwh=f.matched_mwh,
            surplus_mwh=f.surplus_mwh,
        )
        for f in outcome.farms
    ]

    return HourlyMatchingResult(
        period=period,
        modeled=True,
        note=_MODELED_NOTE,
        hours=outcome.hours,
        cfe_percent=outcome.cfe_percent,
        paper_re_percent=paper.cfe_percent,
        total_consumption_mwh=outcome.total_consumption_mwh,
        total_matched_mwh=outcome.total_matched_mwh,
        total_surplus_mwh=sum(outcome.surplus_by_hour),
        total_shortfall_mwh=sum(outcome.shortfall_by_hour),
        generation_by_hour=outcome.generation_by_hour,
        consumption_by_hour=outcome.consumption_by_hour,
        matched_by_hour=outcome.matched_by_hour,
        surplus_by_hour=outcome.surplus_by_hour,
        shortfall_by_hour=outcome.shortfall_by_hour,
        customers=customers_out,
        farms=farms_out,
    )
