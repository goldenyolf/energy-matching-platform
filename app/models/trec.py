"""T-REC certificate batch (1 憑證 = 1,000 度 = 1 MWh)."""

from __future__ import annotations

from sqlalchemy import Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.models.customer import Customer
from app.models.wind_farm import WindFarm


class TrecBatch(Base, TimestampMixin):
    __tablename__ = "trec_batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_no: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    wind_farm_id: Mapped[int] = mapped_column(ForeignKey("wind_farms.id"), index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    period: Mapped[str] = mapped_column(String(7), index=True)
    quantity_mwh: Mapped[float] = mapped_column(Float)
    # plain String (not a DB enum) — avoids the Postgres CREATE TYPE migration trap
    status: Mapped[str] = mapped_column(String(20), default="transferred")

    wind_farm: Mapped[WindFarm] = relationship()
    customer: Mapped[Customer] = relationship()
