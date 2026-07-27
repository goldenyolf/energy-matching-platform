"""Meter (電號/廠區) endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_write_access
from app.schemas.meter import MeterCreate, MeterRead, MeterUpdate
from app.services import meter_service as svc

router = APIRouter(prefix="/meters", tags=["meters"])
_write = Depends(require_write_access)


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
