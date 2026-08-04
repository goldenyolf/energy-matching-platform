"""Meter (電號/廠區) endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Query, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, read_upload, require_write_access
from app.ingestion import csv_importer
from app.schemas.common import ImportResult
from app.schemas.meter import MeterCreate, MeterRead, MeterUpdate
from app.services import meter_service as svc

router = APIRouter(prefix="/meters", tags=["meters"])
_write = Depends(require_write_access)


@router.post("/import", response_model=ImportResult, dependencies=[_write])
async def import_meters(
    file: UploadFile = File(..., description="CSV of meter rows"),
    dry_run: bool = Query(False, description="只驗證與預覽，不寫入"),
    db: Session = Depends(get_db),
) -> ImportResult:
    rows = csv_importer.parse_csv(await read_upload(file))
    return csv_importer.import_meters(db, rows, dry_run=dry_run)


@router.get("", response_model=list[MeterRead])
def list_meters(
    customer_id: int | None = Query(default=None),
    limit: int = Query(500, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    return svc.list_all(db, customer_id=customer_id, limit=limit, offset=offset)


@router.post(
    "",
    response_model=MeterRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_write],
)
def create_meter(payload: MeterCreate, db: Session = Depends(get_db)):
    return svc.create(db, payload)


@router.get("/{meter_id}", response_model=MeterRead)
def get_meter(meter_id: int, db: Session = Depends(get_db)):
    return svc.get(db, meter_id)


@router.put("/{meter_id}", response_model=MeterRead, dependencies=[_write])
def update_meter(meter_id: int, payload: MeterUpdate, db: Session = Depends(get_db)):
    return svc.update(db, meter_id, payload)


@router.delete(
    "/{meter_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[_write]
)
def delete_meter(meter_id: int, db: Session = Depends(get_db)) -> None:
    svc.delete(db, meter_id)
