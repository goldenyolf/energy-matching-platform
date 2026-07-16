# app/services/evaluation.py
"""Monthly sales evaluation: reuse the matching engine, add economics.

Pure read-side: runs compute_outcome per month over a period, aggregates the
target customer's allocations, and derives seller (gross margin) and buyer
(RE% / cost) economics. Gross margin excludes wheeling fee (matches the
reference deck). Energy is MWh; economics are computed in kWh.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.models import ConsumptionData, Contract, Customer, WindFarm
from app.schemas.evaluation import BuyerSide, EvaluationResult, SellerSide
from app.services.matching_service import compute_outcome

_KWH = 1000.0


def _periods(
    db: Session, customer_id: int, start: str | None, end: str | None
) -> list[str]:
    rows = db.execute(
        select(ConsumptionData.period_start)
        .where(ConsumptionData.customer_id == customer_id)
        .distinct()
    ).scalars()
    periods = sorted({f"{d.year:04d}-{d.month:02d}" for d in rows})
    if start:
        periods = [p for p in periods if p >= start]
    if end:
        periods = [p for p in periods if p <= end]
    return periods


def evaluate(
    db: Session,
    customer_id: int,
    start: str | None = None,
    end: str | None = None,
) -> EvaluationResult:
    customer = db.get(Customer, customer_id)
    if customer is None:
        raise NotFoundError(f"customer {customer_id} not found")

    default_feed = settings.default_feed_in_price_per_kwh
    grey = settings.grey_price_per_kwh
    farms = {f.id: f for f in db.execute(select(WindFarm)).scalars()}
    contract_price = {
        c.id: (c.price_per_kwh or 0.0) for c in db.execute(select(Contract)).scalars()
    }

    procurement = revenue = green_kwh = green_cost = total_consumption = 0.0
    used_default = False
    periods = _periods(db, customer_id, start, end)

    for period in periods:
        outcome = compute_outcome(db, period)
        for cs in outcome.customer_summaries:
            if cs.customer_id == customer_id:
                total_consumption += cs.consumption_mwh
        for a in outcome.allocations:
            if a.customer_id != customer_id or a.allocated_mwh <= 0:
                continue
            kwh = a.allocated_mwh * _KWH
            farm = farms.get(a.wind_farm_id)
            feed = (
                farm.feed_in_price_per_kwh
                if farm and farm.feed_in_price_per_kwh is not None
                else default_feed
            )
            if farm is None or farm.feed_in_price_per_kwh is None:
                used_default = True
            price = contract_price.get(a.contract_id, 0.0)
            green_kwh += kwh
            procurement += kwh * feed
            revenue += kwh * price
            green_cost += kwh * price

    total_kwh = total_consumption * _KWH
    grey_kwh = max(0.0, total_kwh - green_kwh)
    gross_profit = revenue - procurement
    gross_margin = (gross_profit / revenue * 100.0) if revenue else 0.0
    re_percent = (green_kwh / total_kwh * 100.0) if total_kwh else 0.0
    avg_price = ((green_cost + grey_kwh * grey) / total_kwh) if total_kwh else 0.0
    added_cost = green_cost - green_kwh * grey

    return EvaluationResult(
        customer_id=customer_id,
        customer_code=customer.code,
        company_name=customer.company_name,
        start=periods[0] if periods else (start or ""),
        end=periods[-1] if periods else (end or ""),
        used_default_feed_in_price=used_default,
        seller=SellerSide(
            procurement_cost=round(procurement, 2),
            sales_revenue=round(revenue, 2),
            gross_profit=round(gross_profit, 2),
            gross_margin_percent=round(gross_margin, 4),
        ),
        buyer=BuyerSide(
            total_consumption_mwh=round(total_consumption, 3),
            green_mwh=round(green_kwh / _KWH, 3),
            grey_mwh=round(grey_kwh / _KWH, 3),
            re_percent=round(re_percent, 4),
            avg_price_per_kwh=round(avg_price, 4),
            added_cost=round(added_cost, 2),
        ),
    )
