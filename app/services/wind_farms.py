"""Wind farm service."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError
from app.models import Contract, GenerationData, WindFarm
from app.repositories.base import BaseRepository
from app.schemas.wind_farm import WindFarmCreate, WindFarmUpdate


def _repo(db: Session) -> BaseRepository[WindFarm]:
    return BaseRepository(WindFarm, db)


def create(db: Session, data: WindFarmCreate) -> WindFarm:
    repo = _repo(db)
    if repo.get_by(code=data.code):
        raise ConflictError(f"wind farm code '{data.code}' already exists")
    return repo.create(WindFarm(**data.model_dump()))


def get(db: Session, farm_id: int) -> WindFarm:
    farm = _repo(db).get(farm_id)
    if farm is None:
        raise NotFoundError(f"wind farm {farm_id} not found")
    return farm


def list_all(db: Session, *, limit: int = 100, offset: int = 0) -> list[WindFarm]:
    return _repo(db).list(limit=limit, offset=offset)


def update(db: Session, farm_id: int, data: WindFarmUpdate) -> WindFarm:
    farm = get(db, farm_id)
    return _repo(db).update(farm, data.model_dump(exclude_unset=True))


def delete(db: Session, farm_id: int) -> None:
    """Delete a wind farm, refusing if it still has contracts or generation."""
    farm = get(db, farm_id)
    contracts = db.scalar(
        select(func.count())
        .select_from(Contract)
        .where(Contract.wind_farm_id == farm_id)
    )
    generation = db.scalar(
        select(func.count())
        .select_from(GenerationData)
        .where(GenerationData.wind_farm_id == farm_id)
    )
    if contracts or generation:
        raise ConflictError(
            f"此案場尚有 {contracts or 0} 筆合約、{generation or 0} 筆發電資料,"
            "請先移除關聯資料後再刪除。"
        )
    _repo(db).delete(farm)
