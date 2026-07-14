"""Power Purchase Agreement (green energy contract) ORM model."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import Date, Enum, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.models.enums import ContractStatus

if TYPE_CHECKING:
    from app.models.customer import Customer
    from app.models.wind_farm import WindFarm


class Contract(Base, TimestampMixin):
    __tablename__ = "contracts"

    id: Mapped[int] = mapped_column(primary_key=True)
    contract_number: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    wind_farm_id: Mapped[int] = mapped_column(ForeignKey("wind_farms.id"), index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)

    # A contract caps allocation by a fixed monthly volume and/or a share of the
    # farm's generation. Either or both may be set; the engine uses the tighter.
    contracted_energy_mwh: Mapped[float | None] = mapped_column(Float, default=None)
    contracted_percentage: Mapped[float | None] = mapped_column(Float, default=None)
    price_per_kwh: Mapped[float | None] = mapped_column(Float, default=None)
    priority: Mapped[int] = mapped_column(Integer, default=100)
    status: Mapped[ContractStatus] = mapped_column(
        Enum(ContractStatus), default=ContractStatus.ACTIVE
    )

    wind_farm: Mapped[WindFarm] = relationship(back_populates="contracts")
    customer: Mapped[Customer] = relationship(back_populates="contracts")
