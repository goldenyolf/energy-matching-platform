"""Meter (電號/廠區) CRUD + RE attainment breakdown schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class MeterBase(BaseModel):
    code: str = Field(..., max_length=50)
    customer_id: int
    name: str = Field(..., max_length=200)
    location: str | None = None
    re_target_percent: float = Field(0.0, ge=0, le=100)
    annual_consumption_mwh: float | None = Field(default=None, ge=0)
    # 用電負載數據 (per-電號)
    usage_name: str | None = Field(default=None, max_length=200)
    contracted_capacity_kw: float | None = Field(default=None, ge=0)
    tariff_type: str | None = Field(default=None, max_length=40)
    load_data_type: str | None = Field(default=None, max_length=100)
    peak_kwh: float | None = Field(default=None, ge=0)
    half_peak_kwh: float | None = Field(default=None, ge=0)
    saturday_half_peak_kwh: float | None = Field(default=None, ge=0)
    off_peak_kwh: float | None = Field(default=None, ge=0)
    total_kwh: float | None = Field(default=None, ge=0)
    data_period: str | None = Field(default=None, max_length=40)


class MeterCreate(MeterBase):
    pass


class MeterUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    location: str | None = None
    re_target_percent: float | None = Field(default=None, ge=0, le=100)
    annual_consumption_mwh: float | None = Field(default=None, ge=0)
    usage_name: str | None = Field(default=None, max_length=200)
    contracted_capacity_kw: float | None = Field(default=None, ge=0)
    tariff_type: str | None = Field(default=None, max_length=40)
    load_data_type: str | None = Field(default=None, max_length=100)
    peak_kwh: float | None = Field(default=None, ge=0)
    half_peak_kwh: float | None = Field(default=None, ge=0)
    saturday_half_peak_kwh: float | None = Field(default=None, ge=0)
    off_peak_kwh: float | None = Field(default=None, ge=0)
    total_kwh: float | None = Field(default=None, ge=0)
    data_period: str | None = Field(default=None, max_length=40)


class MeterRead(MeterBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime


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
