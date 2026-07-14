"""Customer request/response schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CustomerBase(BaseModel):
    code: str = Field(..., max_length=50, examples=["CUST-TSMC"])
    company_name: str = Field(..., max_length=200)
    industry: str | None = None
    annual_consumption_mwh: float = Field(0.0, ge=0)
    re_target_percent: float = Field(0.0, ge=0, le=100)
    target_year: int | None = Field(default=None, ge=2000, le=2100)


class CustomerCreate(CustomerBase):
    pass


class CustomerUpdate(BaseModel):
    company_name: str | None = None
    industry: str | None = None
    annual_consumption_mwh: float | None = Field(default=None, ge=0)
    re_target_percent: float | None = Field(default=None, ge=0, le=100)
    target_year: int | None = Field(default=None, ge=2000, le=2100)


class CustomerRead(CustomerBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime
