"""Contract (PPA) request/response schemas."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import ContractStatus


class ContractBase(BaseModel):
    contract_number: str = Field(..., max_length=50, examples=["PPA-2024-001"])
    wind_farm_id: int
    customer_id: int
    start_date: date
    end_date: date
    contracted_energy_mwh: float | None = Field(default=None, ge=0)
    contracted_percentage: float | None = Field(default=None, ge=0, le=100)
    price_per_kwh: float | None = Field(default=None, ge=0)
    priority: int = Field(100, ge=1, description="Lower value = higher priority")
    status: ContractStatus = ContractStatus.ACTIVE

    @model_validator(mode="after")
    def _check(self) -> ContractBase:
        if self.end_date < self.start_date:
            raise ValueError("end_date must not be before start_date")
        if self.contracted_energy_mwh is None and self.contracted_percentage is None:
            raise ValueError(
                "at least one of contracted_energy_mwh or "
                "contracted_percentage must be provided"
            )
        return self


class ContractCreate(ContractBase):
    pass


class ContractUpdate(BaseModel):
    start_date: date | None = None
    end_date: date | None = None
    contracted_energy_mwh: float | None = Field(default=None, ge=0)
    contracted_percentage: float | None = Field(default=None, ge=0, le=100)
    price_per_kwh: float | None = Field(default=None, ge=0)
    priority: int | None = Field(default=None, ge=1)
    status: ContractStatus | None = None


class ContractRead(ContractBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime
