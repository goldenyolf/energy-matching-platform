"""Contract risk alert schema."""

from __future__ import annotations

from pydantic import BaseModel


class RiskAlert(BaseModel):
    severity: str
    category: str
    contract_number: str | None
    wind_farm_code: str | None
    customer_code: str | None
    title: str
    detail: str
    suggested_action: str


class RiskCounts(BaseModel):
    high: int
    medium: int
    low: int
    total: int


class RiskReport(BaseModel):
    period: str
    reference_date: str
    horizon_months: int
    counts: RiskCounts
    alerts: list[RiskAlert]
