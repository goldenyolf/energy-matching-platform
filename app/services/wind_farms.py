"""Wind farm service."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError
from app.models import WindFarm
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
