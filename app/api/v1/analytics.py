"""Analytics endpoints (computed on-the-fly for a period)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.config import settings
from app.schemas.analytics import (
    CustomerAnalytics,
    PeriodSummary,
    WindFarmAnalytics,
)
from app.schemas.customer_optimization import CustomerOptimizationResult
from app.schemas.evaluation import EvaluationResult
from app.schemas.investment import InvestmentResult
from app.schemas.settlement import SettlementResult
from app.services import analytics_service as svc
from app.services import customer_optimization_service as copt_svc
from app.services import evaluation as eval_svc
from app.services import investment_service as inv_svc
from app.services import settlement_service as settle_svc
from app.services.customer_optimization_service import CustomerOptimizeOptions
from app.services.settlement_service import SettlementOptions

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


@router.get("/evaluation", response_model=EvaluationResult)
def evaluation(
    customer_id: int = Query(..., ge=1),
    start: str | None = Query(None, examples=["2025-01"]),
    end: str | None = Query(None, examples=["2025-12"]),
    db: Session = Depends(get_db),
) -> EvaluationResult:
    return eval_svc.evaluate(db, customer_id, start=start, end=end)


@router.get("/customer-optimization", response_model=CustomerOptimizationResult)
def customer_optimization(
    customer_id: int = Query(..., ge=1),
    period: str = _period,
    min_sites: int | None = Query(None, ge=0),
    min_site_allocation_percent: float | None = Query(None, ge=0.0, le=100.0),
    re_target_percent: float | None = Query(None, ge=0.0, le=100.0),
    transfer_price_per_kwh: float | None = Query(None, ge=0.0),
    db: Session = Depends(get_db),
) -> CustomerOptimizationResult:
    """Unified per-customer optimization: one MILP run feeds every panel."""
    opts = CustomerOptimizeOptions(
        min_sites_per_customer=(
            settings.optimize_min_sites_per_customer if min_sites is None else min_sites
        ),
        min_site_allocation_percent=(
            settings.optimize_min_site_allocation_percent
            if min_site_allocation_percent is None
            else min_site_allocation_percent
        ),
        re_target_percent=re_target_percent,
        transfer_price_per_kwh=transfer_price_per_kwh,
    )
    return copt_svc.compute_customer_optimization(db, customer_id, period, opts)


@router.get("/investment", response_model=InvestmentResult)
def investment(
    capex_per_mw: float | None = Query(None, gt=0.0),
    om_rate_percent: float | None = Query(None, ge=0.0, le=100.0),
    db: Session = Depends(get_db),
) -> InvestmentResult:
    """Per-farm and portfolio ROI / payback. CAPEX and O&M rate overridable."""
    return inv_svc.compute_investment(
        db,
        capex_per_mw=(settings.capex_per_mw if capex_per_mw is None else capex_per_mw),
        om_rate_percent=(
            settings.om_rate_percent if om_rate_percent is None else om_rate_percent
        ),
    )


@router.get("/settlement", response_model=SettlementResult)
def settlement(
    customer_id: int = Query(..., ge=1),
    period: str = _period,
    transfer_price_per_kwh: float | None = Query(None, ge=0.0),
    wheeling_fee_per_kwh: float | None = Query(None, ge=0.0),
    db: Session = Depends(get_db),
) -> SettlementResult:
    """Two-sided per-slot 轉供結算單 for a customer/period."""
    return settle_svc.compute_settlement(
        db,
        customer_id,
        period,
        SettlementOptions(
            transfer_price_per_kwh=transfer_price_per_kwh,
            wheeling_fee_per_kwh=wheeling_fee_per_kwh,
        ),
    )
