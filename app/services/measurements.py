"""Generation and consumption data services."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import ValidationError
from app.models import ConsumptionData, Customer, GenerationData, WindFarm
from app.schemas.consumption import ConsumptionCreate
from app.schemas.generation import GenerationCreate


def create_generation(db: Session, data: GenerationCreate) -> GenerationData:
    if db.get(WindFarm, data.wind_farm_id) is None:
        raise ValidationError(f"wind_farm_id {data.wind_farm_id} does not exist")
    row = GenerationData(**data.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def list_generation(
    db: Session,
    *,
    wind_farm_id: int | None = None,
    limit: int = 500,
    offset: int = 0,
) -> list[GenerationData]:
    stmt = select(GenerationData)
    if wind_farm_id is not None:
        stmt = stmt.where(GenerationData.wind_farm_id == wind_farm_id)
    stmt = stmt.order_by(GenerationData.period_start).offset(offset).limit(limit)
    return list(db.execute(stmt).scalars().all())


def create_consumption(db: Session, data: ConsumptionCreate) -> ConsumptionData:
    if db.get(Customer, data.customer_id) is None:
        raise ValidationError(f"customer_id {data.customer_id} does not exist")
    row = ConsumptionData(**data.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def list_consumption(
    db: Session,
    *,
    customer_id: int | None = None,
    limit: int = 500,
    offset: int = 0,
) -> list[ConsumptionData]:
    stmt = select(ConsumptionData)
    if customer_id is not None:
        stmt = stmt.where(ConsumptionData.customer_id == customer_id)
    stmt = stmt.order_by(ConsumptionData.period_start).offset(offset).limit(limit)
    return list(db.execute(stmt).scalars().all())
