"""Wind farm request/response schemas."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import WindFarmStatus


class WindFarmBase(BaseModel):
    code: str = Field(..., max_length=50, examples=["WF-FORMOSA2"])
    name: str = Field(..., max_length=200)
    operator_name: str | None = None
    location: str | None = None
    installed_capacity_mw: float = Field(..., gt=0)
    feed_in_price_per_kwh: float | None = Field(default=None, ge=0)
    commercial_operation_date: date | None = None
    status: WindFarmStatus = WindFarmStatus.OPERATIONAL


class WindFarmCreate(WindFarmBase):
    pass


class WindFarmUpdate(BaseModel):
    name: str | None = None
    operator_name: str | None = None
    location: str | None = None
    installed_capacity_mw: float | None = Field(default=None, gt=0)
    commercial_operation_date: date | None = None
    status: WindFarmStatus | None = None


class WindFarmRead(WindFarmBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime
