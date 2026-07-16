"""Response schema for the economic-optimization endpoint (P3)."""

from __future__ import annotations

from pydantic import BaseModel


class OptAllocation(BaseModel):
    contract_id: int
    contract_number: str
    wind_farm_id: int
    customer_id: int
    allocated_mwh: float
    contract_limit_mwh: float | None
    reason: str


class OptCustomerTarget(BaseModel):
    customer_id: int
    re_target_mwh: float
    allocated_mwh: float
    re_shortfall_mwh: float
    re_target_met: bool
    sites_used: int
    site_shortfall: int


class OptCustomerSummary(BaseModel):
    customer_id: int
    consumption_mwh: float
    allocated_mwh: float
    achieved_re_percent: float


class OptFarmSummary(BaseModel):
    wind_farm_id: int
    generated_mwh: float
    allocated_mwh: float
    unallocated_mwh: float


class OptimizationResult(BaseModel):
    period: str
    solver_status: str
    objective_gross_margin_ntd: float
    min_sites_per_customer: int
    min_site_allocation_percent: float
    allocations: list[OptAllocation]
    customer_targets: list[OptCustomerTarget]
    customer_summaries: list[OptCustomerSummary]
    farm_summaries: list[OptFarmSummary]
