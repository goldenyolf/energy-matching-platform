"""Battery (客戶側儲能) endpoints (A8)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Query, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, read_upload, require_write_access
from app.ingestion import csv_importer
from app.schemas.battery import BatteryCreate, BatteryRead, BatteryUpdate
from app.schemas.common import ImportResult
from app.services import battery_service as svc

router = APIRouter(prefix="/batteries", tags=["batteries"])
_write = Depends(require_write_access)


@router.post("/import", response_model=ImportResult, dependencies=[_write])
async def import_batteries(
    file: UploadFile = File(..., description="CSV of battery rows"),
    dry_run: bool = Query(False, description="只驗證與預覽，不寫入"),
    db: Session = Depends(get_db),
) -> ImportResult:
    rows = csv_importer.parse_csv(await read_upload(file))
    return csv_importer.import_batteries(db, rows, dry_run=dry_run)


@router.get("", response_model=list[BatteryRead])
def list_batteries(
    customer_id: int | None = Query(default=None),
    limit: int = Query(500, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    return svc.list_all(db, customer_id=customer_id, limit=limit, offset=offset)


@router.post(
    "",
    response_model=BatteryRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_write],
)
def create_battery(payload: BatteryCreate, db: Session = Depends(get_db)):
    return svc.create(db, payload)


@router.get("/{battery_id}", response_model=BatteryRead)
def get_battery(battery_id: int, db: Session = Depends(get_db)):
    return svc.get(db, battery_id)


@router.put("/{battery_id}", response_model=BatteryRead, dependencies=[_write])
def update_battery(
    battery_id: int, payload: BatteryUpdate, db: Session = Depends(get_db)
):
    return svc.update(db, battery_id, payload)


@router.delete(
    "/{battery_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[_write]
)
def delete_battery(battery_id: int, db: Session = Depends(get_db)) -> None:
    svc.delete(db, battery_id)
