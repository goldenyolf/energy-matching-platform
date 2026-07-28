"""Meter (電號/廠區) — a demand-side sub-unit of a customer."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.customer import Customer


class Meter(Base, TimestampMixin):
    __tablename__ = "meters"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    location: Mapped[str | None] = mapped_column(String(200), default=None)
    re_target_percent: Mapped[float] = mapped_column(Float, default=0.0)
    annual_consumption_mwh: Mapped[float | None] = mapped_column(Float, default=None)

    # 用電負載數據 (per-電號): capacity, Taipower TOU plan, and the annual
    # per-time-slot consumption incl. Saturday half-peak. ``total_kwh`` drives
    # each meter's share of consumption in the RE-attainment breakdown, and the
    # slot fields drive its time-of-use split there (周六半尖峰 folds into 半尖峰
    # for the 3-slot view). See app/services/meter_service.py.
    usage_name: Mapped[str | None] = mapped_column(String(200), default=None)
    contracted_capacity_kw: Mapped[float | None] = mapped_column(Float, default=None)
    tariff_type: Mapped[str | None] = mapped_column(String(40), default=None)
    load_data_type: Mapped[str | None] = mapped_column(String(100), default=None)
    peak_kwh: Mapped[float | None] = mapped_column(Float, default=None)
    half_peak_kwh: Mapped[float | None] = mapped_column(Float, default=None)
    saturday_half_peak_kwh: Mapped[float | None] = mapped_column(Float, default=None)
    off_peak_kwh: Mapped[float | None] = mapped_column(Float, default=None)
    total_kwh: Mapped[float | None] = mapped_column(Float, default=None)
    data_period: Mapped[str | None] = mapped_column(String(40), default=None)

    customer: Mapped[Customer] = relationship(back_populates="meters")
