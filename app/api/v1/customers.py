"""Customer endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Query, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, read_upload, require_write_access
from app.ingestion import csv_importer
from app.schemas.common import ImportResult
from app.schemas.customer import CustomerCreate, CustomerRead, CustomerUpdate
from app.services import customers as svc

router = APIRouter(prefix="/customers", tags=["customers"])
_write = Depends(require_write_access)


@router.post("/import", response_model=ImportResult, dependencies=[_write])
async def import_customers(
    file: UploadFile = File(..., description="CSV of customer rows"),
    dry_run: bool = Query(False, description="只驗證與預覽，不寫入"),
    db: Session = Depends(get_db),
) -> ImportResult:
    rows = csv_importer.parse_csv(await read_upload(file))
    return csv_importer.import_customers(db, rows, dry_run=dry_run)


@router.get("", response_model=list[CustomerRead])
def list_customers(
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    return svc.list_all(db, limit=limit, offset=offset)


@router.post(
    "",
    response_model=CustomerRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_write],
)
def create_customer(payload: CustomerCreate, db: Session = Depends(get_db)):
    return svc.create(db, payload)


@router.get("/{customer_id}", response_model=CustomerRead)
def get_customer(customer_id: int, db: Session = Depends(get_db)):
    return svc.get(db, customer_id)


@router.put("/{customer_id}", response_model=CustomerRead, dependencies=[_write])
def update_customer(
    customer_id: int, payload: CustomerUpdate, db: Session = Depends(get_db)
):
    return svc.update(db, customer_id, payload)


@router.delete(
    "/{customer_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[_write]
)
def delete_customer(customer_id: int, db: Session = Depends(get_db)) -> None:
    svc.delete(db, customer_id)
