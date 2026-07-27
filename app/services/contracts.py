"""Contract (PPA) service."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.models import Contract, Customer, MatchingResult, WindFarm
from app.repositories.base import BaseRepository
from app.schemas.contract import ContractCreate, ContractUpdate


def _repo(db: Session) -> BaseRepository[Contract]:
    return BaseRepository(Contract, db)


def create(db: Session, data: ContractCreate) -> Contract:
    repo = _repo(db)
    if repo.get_by(contract_number=data.contract_number):
        raise ConflictError(f"contract number '{data.contract_number}' already exists")
    if db.get(WindFarm, data.wind_farm_id) is None:
        raise ValidationError(f"wind_farm_id {data.wind_farm_id} does not exist")
    if db.get(Customer, data.customer_id) is None:
        raise ValidationError(f"customer_id {data.customer_id} does not exist")
    return repo.create(Contract(**data.model_dump()))


def get(db: Session, contract_id: int) -> Contract:
    contract = _repo(db).get(contract_id)
    if contract is None:
        raise NotFoundError(f"contract {contract_id} not found")
    return contract


def list_all(db: Session, *, limit: int = 100, offset: int = 0) -> list[Contract]:
    return _repo(db).list(limit=limit, offset=offset)


def update(db: Session, contract_id: int, data: ContractUpdate) -> Contract:
    contract = get(db, contract_id)
    return _repo(db).update(contract, data.model_dump(exclude_unset=True))


def delete(db: Session, contract_id: int) -> None:
    """Delete a contract, refusing if it is referenced by matching results."""
    contract = get(db, contract_id)
    results = db.scalar(
        select(func.count())
        .select_from(MatchingResult)
        .where(MatchingResult.contract_id == contract_id)
    )
    if results:
        raise ConflictError(
            f"此合約尚有 {results} 筆媒合結果引用,請先移除關聯資料後再刪除。"
        )
    _repo(db).delete(contract)
