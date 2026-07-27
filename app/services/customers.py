"""Customer service."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError
from app.models import ConsumptionData, Contract, Customer, Meter
from app.repositories.base import BaseRepository
from app.schemas.customer import CustomerCreate, CustomerUpdate


def _repo(db: Session) -> BaseRepository[Customer]:
    return BaseRepository(Customer, db)


def create(db: Session, data: CustomerCreate) -> Customer:
    repo = _repo(db)
    if repo.get_by(code=data.code):
        raise ConflictError(f"customer code '{data.code}' already exists")
    return repo.create(Customer(**data.model_dump()))


def get(db: Session, customer_id: int) -> Customer:
    customer = _repo(db).get(customer_id)
    if customer is None:
        raise NotFoundError(f"customer {customer_id} not found")
    return customer


def list_all(db: Session, *, limit: int = 100, offset: int = 0) -> list[Customer]:
    return _repo(db).list(limit=limit, offset=offset)


def update(db: Session, customer_id: int, data: CustomerUpdate) -> Customer:
    customer = get(db, customer_id)
    return _repo(db).update(customer, data.model_dump(exclude_unset=True))


def delete(db: Session, customer_id: int) -> None:
    """Delete a customer, refusing if it still has contracts, consumption, or meters."""
    customer = get(db, customer_id)

    def _count(model, col) -> int:
        return (
            db.scalar(select(func.count()).select_from(model).where(col == customer_id))
            or 0
        )

    contracts = _count(Contract, Contract.customer_id)
    consumption = _count(ConsumptionData, ConsumptionData.customer_id)
    meters = _count(Meter, Meter.customer_id)
    if contracts or consumption or meters:
        raise ConflictError(
            f"此客戶尚有 {contracts} 筆合約、{consumption} 筆用電資料、{meters} 個電號,"
            "請先移除關聯資料後再刪除。"
        )
    _repo(db).delete(customer)
