"""Wind farm generation data ORM model."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import Date, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CreatedMixin

if TYPE_CHECKING:
    from app.models.wind_farm import WindFarm


class GenerationData(Base, CreatedMixin):
    __tablename__ = "generation_data"

    id: Mapped[int] = mapped_column(primary_key=True)
    wind_farm_id: Mapped[int] = mapped_column(ForeignKey("wind_farms.id"), index=True)
    period_start: Mapped[date] = mapped_column(Date, index=True)
    period_end: Mapped[date] = mapped_column(Date)
    generated_energy_mwh: Mapped[float] = mapped_column(Float)
    data_source: Mapped[str] = mapped_column(String(100), default="mock")

    wind_farm: Mapped[WindFarm] = relationship(back_populates="generation")
