"""Customer consumption data ORM model."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import Date, Float, ForeignKey, String
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CreatedMixin
from app.models.enums import TimeSlot

if TYPE_CHECKING:
    from app.models.customer import Customer


class ConsumptionData(Base, CreatedMixin):
    __tablename__ = "consumption_data"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    meter_id: Mapped[int | None] = mapped_column(
        ForeignKey("meters.id"), index=True, nullable=True, default=None
    )
    period_start: Mapped[date] = mapped_column(Date, index=True)
    period_end: Mapped[date] = mapped_column(Date)
    consumed_energy_mwh: Mapped[float] = mapped_column(Float)
    data_source: Mapped[str] = mapped_column(String(100), default="mock")
    time_slot: Mapped[TimeSlot | None] = mapped_column(
        SAEnum(TimeSlot), default=None, nullable=True
    )

    customer: Mapped[Customer] = relationship(back_populates="consumption")
