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

    customer: Mapped[Customer] = relationship(back_populates="meters")
