"""Matching run/result endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.config import settings
from app.matching.optimizer import OptimizeOptions
from app.schemas.matching import (
    MatchingResultRead,
    MatchingRunCreate,
    MatchingRunDetail,
    MatchingRunRead,
)
from app.schemas.optimization import OptimizationResult
from app.schemas.slot_matching import SlotMatchingResult
from app.services import matching_service as svc
from app.services import optimize_service, slot_matching_service

router = APIRouter(prefix="/matching", tags=["matching"])


@router.post(
    "/runs", response_model=MatchingRunDetail, status_code=status.HTTP_201_CREATED
)
def create_run(payload: MatchingRunCreate, db: Session = Depends(get_db)):
    """Run the deterministic matching engine for a period and persist results."""
    return svc.run_matching(db, payload.period)


@router.get("/runs", response_model=list[MatchingRunRead])
def list_runs(
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    return svc.list_runs(db, limit=limit, offset=offset)


@router.get("/runs/{run_id}", response_model=MatchingRunDetail)
def get_run(run_id: int, db: Session = Depends(get_db)):
    run = svc.get_run(db, run_id)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"matching run {run_id} not found",
        )
    return run


@router.get("/results", response_model=list[MatchingResultRead])
def list_results(
    run_id: int | None = Query(default=None),
    period: str | None = Query(default=None),
    limit: int = Query(500, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    return svc.list_results(
        db, run_id=run_id, period=period, limit=limit, offset=offset
    )


@router.get("/optimize", response_model=OptimizationResult)
def optimize(
    period: str = Query(..., examples=["2024-01"], description="Period 'YYYY-MM'"),
    min_sites: int | None = Query(default=None, ge=0),
    min_site_allocation_percent: float | None = Query(default=None, ge=0.0, le=100.0),
    db: Session = Depends(get_db),
) -> OptimizationResult:
    """Global economic-optimization matching for a period (compute-only)."""
    options = OptimizeOptions(
        min_sites_per_customer=(
            settings.optimize_min_sites_per_customer if min_sites is None else min_sites
        ),
        min_site_allocation_percent=(
            settings.optimize_min_site_allocation_percent
            if min_site_allocation_percent is None
            else min_site_allocation_percent
        ),
        default_feed_in_price_per_kwh=settings.default_feed_in_price_per_kwh,
    )
    return optimize_service.compute_optimized(db, period, options)


@router.get("/slots", response_model=SlotMatchingResult)
def slots(
    period: str = Query(..., examples=["2024-01"], description="Period 'YYYY-MM'"),
    db: Session = Depends(get_db),
) -> SlotMatchingResult:
    """Per-time-slot (TOU) matching for a period (compute-only)."""
    return slot_matching_service.compute_slot_outcome(db, period)
