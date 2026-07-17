"""Investment analysis (ROI / payback) response schema."""

from __future__ import annotations

from pydantic import BaseModel


class FarmInvestment(BaseModel):
    wind_farm_id: int
    code: str
    name: str
    capacity_mw: float
    annual_generation_mwh: float
    selling_price_per_kwh: float
    annual_revenue: float
    capex: float
    annual_om: float
    annual_net: float
    roi_percent: float
    payback_years: float | None


class InvestmentTotal(BaseModel):
    capacity_mw: float
    annual_generation_mwh: float
    annual_revenue: float
    capex: float
    annual_om: float
    annual_net: float
    roi_percent: float
    payback_years: float | None


class InvestmentResult(BaseModel):
    capex_per_mw: float
    om_rate_percent: float
    farms: list[FarmInvestment]
    total: InvestmentTotal
