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
from app.schemas.scenario import ScenarioResult
from app.schemas.slot_matching import SlotMatchingResult
from app.services import matching_service as svc
from app.services import optimize_service, scenario_service, slot_matching_service
from app.services.scenario_service import ScenarioRequest

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


def _parse_id_set(raw: str | None) -> set[int] | None:
    """Parse a comma-separated id list; None/empty → None (means 'all')."""
    if raw is None or not raw.strip():
        return None
    ids: set[int] = set()
    for tok in raw.split(","):
        tok = tok.strip()
        if not tok:
            continue
        try:
            ids.add(int(tok))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"invalid id '{tok}'") from exc
    return ids or None


def _parse_float_map(
    raw: str | None, lo: float, hi: float, name: str
) -> dict[int, float]:
    """Parse an 'id:value,id:value' override string into {id: value}."""
    out: dict[int, float] = {}
    if raw is None or not raw.strip():
        return out
    for tok in raw.split(","):
        tok = tok.strip()
        if not tok:
            continue
        try:
            key_s, val_s = tok.split(":")
            val = float(val_s)
        except ValueError as exc:
            raise HTTPException(
                status_code=422, detail=f"invalid {name} '{tok}' (want id:value)"
            ) from exc
        if not lo <= val <= hi:
            raise HTTPException(status_code=422, detail=f"{name} out of range: {val}")
        out[int(key_s)] = val
    return out


@router.get("/scenario", response_model=ScenarioResult)
def scenario(
    period: str = Query(..., examples=["2024-01"], description="Period 'YYYY-MM'"),
    farm_ids: str | None = Query(None, description="CSV of farm ids; empty = all"),
    customer_ids: str | None = Query(None, description="CSV of customer ids"),
    re_targets: str | None = Query(
        None, description="RE-target overrides 'cid:pct,cid:pct'"
    ),
    feed_ins: str | None = Query(
        None, description="Per-farm feed-in overrides 'fid:price,fid:price'"
    ),
    transfer_price: float | None = Query(None, ge=0.0),
    min_sites: int | None = Query(None, ge=0),
    min_site_allocation_percent: float | None = Query(None, ge=0.0, le=100.0),
    db: Session = Depends(get_db),
) -> ScenarioResult:
    """Greenfield 'what-if' matching: any selected farm may supply any selected
    customer (hypothetical pairings) under a single assumed transfer price,
    subject to per-customer RE targets. Compute-only."""
    req = ScenarioRequest(
        farm_ids=_parse_id_set(farm_ids),
        customer_ids=_parse_id_set(customer_ids),
        re_target_overrides=_parse_float_map(re_targets, 0.0, 100.0, "re_target"),
        feed_in_overrides=_parse_float_map(feed_ins, 0.0, 100.0, "feed_in"),
        assumed_transfer_price_per_kwh=(
            settings.scenario_transfer_price_per_kwh
            if transfer_price is None
            else transfer_price
        ),
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
    return scenario_service.compute_scenario(db, period, req)


@router.get("/slots", response_model=SlotMatchingResult)
def slots(
    period: str = Query(..., examples=["2024-01"], description="Period 'YYYY-MM'"),
    db: Session = Depends(get_db),
) -> SlotMatchingResult:
    """Per-time-slot (TOU) matching for a period (compute-only)."""
    return slot_matching_service.compute_slot_outcome(db, period)
