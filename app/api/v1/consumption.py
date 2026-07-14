"""Consumption data endpoints (single create, CSV import, list)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Query, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.ingestion import csv_importer
from app.schemas.common import ImportResult
from app.schemas.consumption import ConsumptionCreate, ConsumptionRead
from app.services import measurements as svc

router = APIRouter(prefix="/consumption", tags=["consumption"])


@router.get("", response_model=list[ConsumptionRead])
def list_consumption(
    customer_id: int | None = Query(default=None),
    limit: int = Query(500, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    return svc.list_consumption(db, customer_id=customer_id, limit=limit, offset=offset)


@router.post("", response_model=ConsumptionRead, status_code=status.HTTP_201_CREATED)
def create_consumption(payload: ConsumptionCreate, db: Session = Depends(get_db)):
    return svc.create_consumption(db, payload)


@router.post("/import", response_model=ImportResult)
async def import_consumption(
    file: UploadFile = File(..., description="CSV file of consumption rows"),
    db: Session = Depends(get_db),
) -> ImportResult:
    rows = csv_importer.parse_csv(await file.read())
    return csv_importer.import_consumption(db, rows)
