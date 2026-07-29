"""Battery CRUD (A8). Thin layer over the generic repository, mirroring
``meter_service`` — the storage maths lives in ``app/matching/storage.py``."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError
from app.models import Battery
from app.repositories.base import BaseRepository
from app.schemas.battery import BatteryCreate, BatteryUpdate


def _repo(db: Session) -> BaseRepository[Battery]:
    return BaseRepository(Battery, db)


def create(db: Session, data: BatteryCreate) -> Battery:
    repo = _repo(db)
    if repo.get_by(code=data.code):
        raise ConflictError(f"儲能代碼 '{data.code}' 已存在")
    return repo.create(Battery(**data.model_dump()))


def get(db: Session, battery_id: int) -> Battery:
    row = _repo(db).get(battery_id)
    if row is None:
        raise NotFoundError(f"找不到儲能 id={battery_id}")
    return row


def list_all(
    db: Session,
    *,
    customer_id: int | None = None,
    limit: int = 500,
    offset: int = 0,
) -> list[Battery]:
    stmt = select(Battery).order_by(Battery.id)
    if customer_id is not None:
        stmt = stmt.where(Battery.customer_id == customer_id)
    return list(db.execute(stmt.offset(offset).limit(limit)).scalars().all())


def update(db: Session, battery_id: int, data: BatteryUpdate) -> Battery:
    row = get(db, battery_id)
    return _repo(db).update(row, data.model_dump(exclude_unset=True))


def delete(db: Session, battery_id: int) -> None:
    _repo(db).delete(get(db, battery_id))
