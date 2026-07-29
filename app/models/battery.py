"""Battery (客戶側儲能) — a behind-the-meter storage asset owned by a customer.

Storage is what lets green energy cross an hour boundary: it charges from green
that would otherwise spill and discharges into the customer's shortfall. The
matching engine itself stays strictly within-the-hour; see
``app/matching/storage.py`` for the layer that sits on top of its output.

Every column is a String/Float — no SQLAlchemy ``Enum`` — to avoid the Postgres
CREATE TYPE trap on managed deploys (same reason as ``wind_farms.farm_type``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.customer import Customer


class Battery(Base, TimestampMixin):
    __tablename__ = "batteries"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))

    # 容量與功率：充放對稱（power_mw 同時是充電與放電的每小時上限）。
    energy_capacity_mwh: Mapped[float] = mapped_column(Float)
    power_mw: Mapped[float] = mapped_column(Float)
    # 往返效率：充電 1:1 進 SOC、放電送出 SOC × η（損耗一次記在放電端，便於對帳）。
    round_trip_efficiency_percent: Mapped[float] = mapped_column(Float, default=88.0)
    initial_soc_percent: Mapped[float] = mapped_column(Float, default=0.0)

    customer: Mapped[Customer] = relationship(back_populates="batteries")
