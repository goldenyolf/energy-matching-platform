"""Wind farm ORM model."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import Date, Enum, Float, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.models.enums import WindFarmStatus

if TYPE_CHECKING:
    from app.models.contract import Contract
    from app.models.generation import GenerationData


class WindFarm(Base, TimestampMixin):
    __tablename__ = "wind_farms"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    operator_name: Mapped[str | None] = mapped_column(String(200), default=None)
    location: Mapped[str | None] = mapped_column(String(200), default=None)
    installed_capacity_mw: Mapped[float] = mapped_column(Float)
    commercial_operation_date: Mapped[date | None] = mapped_column(Date, default=None)
    status: Mapped[WindFarmStatus] = mapped_column(
        Enum(WindFarmStatus), default=WindFarmStatus.OPERATIONAL
    )

    contracts: Mapped[list[Contract]] = relationship(
        back_populates="wind_farm", cascade="all, delete-orphan"
    )
    generation: Mapped[list[GenerationData]] = relationship(
        back_populates="wind_farm", cascade="all, delete-orphan"
    )
