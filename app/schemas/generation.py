"""Generation data request/response schemas."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator


class GenerationBase(BaseModel):
    wind_farm_id: int
    period_start: date
    period_end: date
    generated_energy_mwh: float = Field(..., ge=0)
    data_source: str = "mock"

    @model_validator(mode="after")
    def _check(self) -> GenerationBase:
        if self.period_end < self.period_start:
            raise ValueError("period_end must not be before period_start")
        return self


class GenerationCreate(GenerationBase):
    pass


class GenerationRead(GenerationBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
