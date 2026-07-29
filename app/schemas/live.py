"""Response schemas for the Taipower real-time renewables endpoint."""

from __future__ import annotations

from pydantic import BaseModel


class LiveUnit(BaseModel):
    name: str
    capacity_mw: float | None = None
    net_mw: float | None = None
    # Taipower's own 淨發電量/裝置容量比 — an *instantaneous* output ratio, not the
    # annual capacity factor (P50/P90) the matching engine uses.
    output_ratio_pct: float | None = None
    # 備註, e.g. 部分檢修 / 新增設備測試運轉 / 運轉限制. Blank cells → None.
    note: str | None = None


class RenewableTypeSummary(BaseModel):
    unit_type: str
    unit_count: int
    net_mw: float


class LiveRenewables(BaseModel):
    snapshot_time: str | None
    source_url: str | None = None
    wind: list[LiveUnit]
    wind_total_mw: float
    renewable_summary: list[RenewableTypeSummary]
    renewable_total_mw: float
