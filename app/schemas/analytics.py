"""Analytics response schemas."""

from __future__ import annotations

from pydantic import BaseModel


class CustomerAnalytics(BaseModel):
    customer_id: int
    code: str
    company_name: str
    period: str
    consumption_mwh: float
    allocated_mwh: float
    achieved_re_percent: float
    re_target_percent: float
    target_energy_mwh: float
    gap_to_target_mwh: float
    target_met: bool


class WindFarmAnalytics(BaseModel):
    wind_farm_id: int
    code: str
    name: str
    period: str
    generated_mwh: float
    allocated_mwh: float
    unallocated_mwh: float
    utilization_percent: float


class ContractUtilization(BaseModel):
    contract_id: int
    contract_number: str
    period: str
    contract_limit_mwh: float | None
    allocated_mwh: float
    utilization_percent: float | None


class PeriodSummary(BaseModel):
    period: str
    total_generation_mwh: float
    total_allocated_mwh: float
    total_unallocated_mwh: float
    total_consumption_mwh: float
    average_re_percent: float
    customer_count: int
    wind_farm_count: int
    customers_meeting_target: int
