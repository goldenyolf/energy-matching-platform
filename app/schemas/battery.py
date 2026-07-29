"""Battery (客戶側儲能) CRUD schemas (A8)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class BatteryBase(BaseModel):
    code: str = Field(..., max_length=50)
    customer_id: int
    name: str = Field(..., max_length=200)
    energy_capacity_mwh: float = Field(..., gt=0)
    power_mw: float = Field(..., gt=0)
    round_trip_efficiency_percent: float = Field(88.0, gt=0, le=100)
    initial_soc_percent: float = Field(0.0, ge=0, le=100)


class BatteryCreate(BatteryBase):
    pass


class BatteryUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    energy_capacity_mwh: float | None = Field(default=None, gt=0)
    power_mw: float | None = Field(default=None, gt=0)
    round_trip_efficiency_percent: float | None = Field(default=None, gt=0, le=100)
    initial_soc_percent: float | None = Field(default=None, ge=0, le=100)


class BatteryRead(BatteryBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime
