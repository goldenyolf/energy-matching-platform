"""Matching run/result endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.schemas.matching import (
    MatchingResultRead,
    MatchingRunCreate,
    MatchingRunDetail,
    MatchingRunRead,
)
from app.services import matching_service as svc

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
