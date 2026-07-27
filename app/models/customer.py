"""Corporate customer ORM model."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Enum as SAEnum
from sqlalchemy import Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.models.enums import GreenTargetType

if TYPE_CHECKING:
    from app.models.consumption import ConsumptionData
    from app.models.contract import Contract
    from app.models.meter import Meter


class Customer(Base, TimestampMixin):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    company_name: Mapped[str] = mapped_column(String(200))
    industry: Mapped[str | None] = mapped_column(String(100), default=None)
    annual_consumption_mwh: Mapped[float] = mapped_column(Float, default=0.0)
    re_target_percent: Mapped[float] = mapped_column(Float, default=0.0)
    target_year: Mapped[int | None] = mapped_column(Integer, default=None)
    green_target_type: Mapped[GreenTargetType] = mapped_column(
        SAEnum(GreenTargetType), default=GreenTargetType.RE_PERCENT
    )
    target_energy_mwh: Mapped[float | None] = mapped_column(Float, default=None)

    # Contract / tariff attributes (stored + editable; not yet wired into calc).
    contracted_capacity_kw: Mapped[float | None] = mapped_column(Float, default=None)
    transfer_price_per_kwh: Mapped[float | None] = mapped_column(Float, default=None)
    # tariff type kept as a plain string (not a DB enum) to avoid the Postgres
    # CREATE TYPE trap on Neon; values: three_stage / two_stage / standard.
    tariff_type: Mapped[str | None] = mapped_column(String(30), default=None)
    peak_price_per_kwh: Mapped[float | None] = mapped_column(Float, default=None)
    half_peak_price_per_kwh: Mapped[float | None] = mapped_column(Float, default=None)
    off_peak_price_per_kwh: Mapped[float | None] = mapped_column(Float, default=None)

    contracts: Mapped[list[Contract]] = relationship(
        back_populates="customer", cascade="all, delete-orphan"
    )
    consumption: Mapped[list[ConsumptionData]] = relationship(
        back_populates="customer", cascade="all, delete-orphan"
    )
    meters: Mapped[list[Meter]] = relationship(
        back_populates="customer", cascade="all, delete-orphan"
    )
