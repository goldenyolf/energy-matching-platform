"""RE target recommendations: cheapest-first surplus farms to close a gap.

Pure analysis layer — reuses the customer/farm analytics; proposes new or
expanded supply from farms that still have unallocated (surplus) green, filling
the customer's RE gap cheapest-first.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.models import Contract, WindFarm
from app.models.enums import ContractStatus
from app.schemas.analytics import WindFarmAnalytics
from app.schemas.recommendation import FarmRecommendation, ReTargetAdvice
from app.services import analytics_service as an

_KWH = 1000.0


def compute_re_recommendations(
    db: Session, customer_id: int, period: str
) -> ReTargetAdvice:
    row = next(
        (c for c in an.customer_analytics(db, period) if c.customer_id == customer_id),
        None,
    )
    if row is None:
        raise NotFoundError(f"customer {customer_id} not found")

    base = {
        "customer_id": row.customer_id,
        "customer_code": row.code,
        "company_name": row.company_name,
        "period": period,
        "re_target_percent": row.re_target_percent,
        "target_energy_mwh": round(row.target_energy_mwh, 3),
        "current_green_mwh": round(row.allocated_mwh, 3),
    }
    gap = row.gap_to_target_mwh
    if gap <= 1e-9:
        return ReTargetAdvice(
            **base,
            gap_mwh=0.0,
            fully_closable=True,
            residual_gap_mwh=0.0,
            total_recommended_mwh=0.0,
            total_est_cost=0.0,
            recommendations=[],
        )

    default_price = settings.default_feed_in_price_per_kwh
    farms = {f.id: f for f in db.execute(select(WindFarm)).scalars()}
    existing = {
        c.wind_farm_id
        for c in db.execute(
            select(Contract).where(
                Contract.customer_id == customer_id,
                Contract.status == ContractStatus.ACTIVE,
            )
        ).scalars()
    }

    def price_of(fa: WindFarmAnalytics) -> float:
        f = farms.get(fa.wind_farm_id)
        p = f.feed_in_price_per_kwh if f else None
        return p if p is not None else default_price

    candidates = [
        fa for fa in an.wind_farm_analytics(db, period) if fa.unallocated_mwh > 1e-9
    ]
    candidates.sort(key=lambda fa: (price_of(fa), -fa.unallocated_mwh))

    recos: list[FarmRecommendation] = []
    remaining = gap
    for fa in candidates:
        if remaining <= 1e-9:
            break
        take = min(fa.unallocated_mwh, remaining)
        p = price_of(fa)
        recos.append(
            FarmRecommendation(
                wind_farm_id=fa.wind_farm_id,
                code=fa.code,
                name=fa.name,
                available_surplus_mwh=round(fa.unallocated_mwh, 3),
                recommended_mwh=round(take, 3),
                gap_covered_percent=round(take / gap * 100.0, 4),
                feed_in_price_per_kwh=round(p, 4),
                est_cost=round(take * _KWH * p, 2),
                has_existing_contract=fa.wind_farm_id in existing,
            )
        )
        remaining -= take

    residual = max(0.0, remaining)
    return ReTargetAdvice(
        **base,
        gap_mwh=round(gap, 3),
        fully_closable=residual <= 1e-9,
        residual_gap_mwh=round(residual, 3),
        total_recommended_mwh=round(sum(x.recommended_mwh for x in recos), 3),
        total_est_cost=round(sum(x.est_cost for x in recos), 2),
        recommendations=recos,
    )
