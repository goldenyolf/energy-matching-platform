"""Matching run and matching result ORM models."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CreatedMixin
from app.models.enums import MatchingRunStatus

if TYPE_CHECKING:
    pass


class MatchingRun(Base, CreatedMixin):
    __tablename__ = "matching_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    period: Mapped[str] = mapped_column(String(7), index=True)  # "YYYY-MM"
    status: Mapped[MatchingRunStatus] = mapped_column(
        Enum(MatchingRunStatus), default=MatchingRunStatus.PENDING
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    input_summary: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    result_summary: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)

    results: Mapped[list[MatchingResult]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class MatchingResult(Base, CreatedMixin):
    __tablename__ = "matching_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    matching_run_id: Mapped[int] = mapped_column(
        ForeignKey("matching_runs.id"), index=True
    )
    wind_farm_id: Mapped[int] = mapped_column(ForeignKey("wind_farms.id"))
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"))
    contract_id: Mapped[int | None] = mapped_column(
        ForeignKey("contracts.id"), default=None
    )
    period: Mapped[str] = mapped_column(String(7), index=True)
    allocated_energy_mwh: Mapped[float] = mapped_column(Float)
    customer_consumption_mwh: Mapped[float] = mapped_column(Float)
    achieved_re_percent: Mapped[float] = mapped_column(Float)
    allocation_reason: Mapped[str] = mapped_column(String(300))

    run: Mapped[MatchingRun] = relationship(back_populates="results")
