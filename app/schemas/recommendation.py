"""RE target recommendation response schema."""

from __future__ import annotations

from pydantic import BaseModel


class FarmRecommendation(BaseModel):
    wind_farm_id: int
    code: str
    name: str
    available_surplus_mwh: float
    recommended_mwh: float
    gap_covered_percent: float
    feed_in_price_per_kwh: float
    est_cost: float
    has_existing_contract: bool


class ReTargetAdvice(BaseModel):
    customer_id: int
    customer_code: str
    company_name: str
    period: str
    re_target_percent: float
    target_energy_mwh: float
    current_green_mwh: float
    gap_mwh: float
    fully_closable: bool
    residual_gap_mwh: float
    total_recommended_mwh: float
    total_est_cost: float
    recommendations: list[FarmRecommendation]
