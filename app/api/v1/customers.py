"""Customer endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_write_access
from app.schemas.customer import CustomerCreate, CustomerRead, CustomerUpdate
from app.services import customers as svc

router = APIRouter(prefix="/customers", tags=["customers"])
_write = Depends(require_write_access)


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
