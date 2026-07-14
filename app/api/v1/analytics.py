"""Analytics endpoints (computed on-the-fly for a period)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.schemas.analytics import (
    CustomerAnalytics,
    PeriodSummary,
    WindFarmAnalytics,
)
from app.services import analytics_service as svc

router = APIRouter(prefix="/analytics", tags=["analytics"])

_period = Query(..., examples=["2024-01"], description="Period 'YYYY-MM'")


@router.get("/customers", response_model=list[CustomerAnalytics])
def customer_analytics(
    period: str = _period, db: Session = Depends(get_db)
) -> list[CustomerAnalytics]:
    return svc.customer_analytics(db, period)


@router.get("/wind-farms", response_model=list[WindFarmAnalytics])
def wind_farm_analytics(
    period: str = _period, db: Session = Depends(get_db)
) -> list[WindFarmAnalytics]:
    return svc.wind_farm_analytics(db, period)


@router.get("/summary", response_model=PeriodSummary)
def period_summary(
    period: str = _period, db: Session = Depends(get_db)
) -> PeriodSummary:
    return svc.period_summary(db, period)
