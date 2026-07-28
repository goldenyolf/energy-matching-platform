"""Contract (PPA) request/response schemas."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import ContractStatus


def _validate_shares(shares: list[float] | None) -> None:
    if shares is not None:
        if len(shares) != 12:
            raise ValueError("monthly_shares must have exactly 12 values")
        if any(s < 0 for s in shares):
            raise ValueError("monthly_shares must be non-negative")
        if sum(shares) <= 0:
            raise ValueError("monthly_shares must sum to a positive value")


class ContractBase(BaseModel):
    contract_number: str = Field(..., max_length=50, examples=["PPA-2024-001"])
    wind_farm_id: int
    customer_id: int
    start_date: date
    end_date: date
    contracted_energy_mwh: float | None = Field(
        default=None, ge=0, description="Annual contracted volume (MWh)"
    )
    contracted_percentage: float | None = Field(default=None, ge=0, le=100)
    price_per_kwh: float | None = Field(default=None, ge=0)
    priority: int = Field(100, ge=1, description="Lower value = higher priority")
    status: ContractStatus = ContractStatus.ACTIVE
    # 合約深化
    monthly_shares: list[float] | None = Field(
        default=None, description="12 monthly weights for the annual volume"
    )
    min_offtake_percent: float | None = Field(default=None, ge=0, le=100)
    price_escalation_percent: float | None = Field(default=None, ge=0, le=100)
    price_base_year: int | None = Field(default=None, ge=2000, le=2100)

    @model_validator(mode="after")
    def _check(self) -> ContractBase:
        if self.end_date < self.start_date:
            raise ValueError("end_date must not be before start_date")
        if self.contracted_energy_mwh is None and self.contracted_percentage is None:
            raise ValueError(
                "at least one of contracted_energy_mwh or "
                "contracted_percentage must be provided"
            )
        _validate_shares(self.monthly_shares)
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
    monthly_shares: list[float] | None = None
    min_offtake_percent: float | None = Field(default=None, ge=0, le=100)
    price_escalation_percent: float | None = Field(default=None, ge=0, le=100)
    price_base_year: int | None = Field(default=None, ge=2000, le=2100)

    @model_validator(mode="after")
    def _check(self) -> ContractUpdate:
        _validate_shares(self.monthly_shares)
        return self


class ContractRead(ContractBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime
