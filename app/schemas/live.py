"""Response schemas for the Taipower real-time renewables endpoint."""

from __future__ import annotations

from pydantic import BaseModel


class LiveUnit(BaseModel):
    name: str
    capacity_mw: float | None = None
    net_mw: float | None = None


class RenewableTypeSummary(BaseModel):
    unit_type: str
    unit_count: int
    net_mw: float


class LiveRenewables(BaseModel):
    snapshot_time: str | None
    wind: list[LiveUnit]
    wind_total_mw: float
    renewable_summary: list[RenewableTypeSummary]
    renewable_total_mw: float
