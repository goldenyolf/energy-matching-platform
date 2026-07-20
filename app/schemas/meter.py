"""Per-meter (電號/廠區) RE attainment breakdown schema."""

from __future__ import annotations

from pydantic import BaseModel


class MeterRow(BaseModel):
    meter_id: int
    code: str
    name: str
    location: str | None
    consumption_mwh: float
    allocated_green_mwh: float
    re_percent: float
    re_target_percent: float
    target_met: bool


class MeterBreakdown(BaseModel):
    customer_id: int
    customer_code: str
    company_name: str
    period: str
    meter_count: int
    total_consumption_mwh: float
    total_green_mwh: float
    customer_re_percent: float
    meters_meeting_target: int
    meters: list[MeterRow]
