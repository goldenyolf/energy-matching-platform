"""Battery (客戶側儲能) endpoints (A8)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_write_access
from app.schemas.battery import BatteryCreate, BatteryRead, BatteryUpdate
from app.services import battery_service as svc

router = APIRouter(prefix="/batteries", tags=["batteries"])
_write = Depends(require_write_access)


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
