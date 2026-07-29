"""Interval (15-minute) meter/generation readings ORM model (B6).

The pipeline for *real* interval data. Each row is one 15-minute interval's
energy for one farm (generation) or customer (consumption), stamped with the
interval-start local time. This is the table real AMI / SCADA exports land in;
until then it is populated with clearly-labelled simulated multi-day data. When
present for a period, the hourly (24/7 CFE) service reads these rows instead of
the modeled typical-day curves, which also unlocks the hour×day heatmap.

``kind`` is a plain String (not an enum) to avoid the Postgres CREATE TYPE trap
on managed deploys.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedMixin

KIND_GENERATION = "generation"
KIND_CONSUMPTION = "consumption"


class IntervalReading(Base, CreatedMixin):
    __tablename__ = "interval_readings"
    __table_args__ = (Index("ix_interval_kind_ref_ts", "kind", "ref_id", "ts"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    # "generation" (ref_id = wind_farm_id) or "consumption" (ref_id = customer_id)
    kind: Mapped[str] = mapped_column(String(16), index=True)
    ref_id: Mapped[int] = mapped_column(Integer, index=True)
    ts: Mapped[datetime] = mapped_column(DateTime, index=True)  # interval start, local
    energy_mwh: Mapped[float] = mapped_column(Float)
    data_source: Mapped[str] = mapped_column(String(100), default="mock")
