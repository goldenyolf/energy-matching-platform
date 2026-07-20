"""T-REC certificate endpoints (ledger + issue/retire lifecycle)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.schemas.trec import TrecBatchOut, TrecLedger
from app.services import trec_service as svc

router = APIRouter(prefix="/trecs", tags=["trecs"])


@router.get("", response_model=TrecLedger)
def ledger(
    period: str | None = Query(None, examples=["2024-01"]),
    customer_id: int | None = Query(None, ge=1),
    db: Session = Depends(get_db),
) -> TrecLedger:
    """T-REC certificate ledger + summary (optionally filtered)."""
    return svc.get_ledger(db, period=period, customer_id=customer_id)


@router.post("/issue", response_model=TrecLedger)
def issue(
    period: str = Query(..., examples=["2024-01"]),
    db: Session = Depends(get_db),
) -> TrecLedger:
    """Issue+transfer certificates for a period from the matching result."""
    svc.issue_for_period(db, period)
    return svc.get_ledger(db, period=period)


@router.post("/{batch_id}/retire", response_model=TrecBatchOut)
def retire_batch(batch_id: int, db: Session = Depends(get_db)) -> TrecBatchOut:
    """Retire a certificate batch (claim RE; not re-tradable)."""
    return svc.batch_to_out(svc.retire(db, batch_id))
