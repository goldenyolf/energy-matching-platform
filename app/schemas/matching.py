"""Matching run/result request/response schemas."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import MatchingRunStatus

_PERIOD_RE = re.compile(r"^\d{4}-\d{2}$")


class MatchingRunCreate(BaseModel):
    period: str = Field(..., examples=["2024-01"], description="YYYY-MM")

    @field_validator("period")
    @classmethod
    def _valid_period(cls, v: str) -> str:
        if not _PERIOD_RE.match(v):
            raise ValueError("period must be in 'YYYY-MM' format")
        month = int(v[5:7])
        if not 1 <= month <= 12:
            raise ValueError("month must be between 01 and 12")
        return v


class MatchingResultRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    matching_run_id: int
    wind_farm_id: int
    customer_id: int
    contract_id: int | None
    period: str
    allocated_energy_mwh: float
    customer_consumption_mwh: float
    achieved_re_percent: float
    allocation_reason: str
    created_at: datetime


class MatchingRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    period: str
    status: MatchingRunStatus
    started_at: datetime | None
    completed_at: datetime | None
    input_summary: dict[str, Any] | None
    result_summary: dict[str, Any] | None
    created_at: datetime


class MatchingRunDetail(MatchingRunRead):
    results: list[MatchingResultRead] = []
