"""Response schema for the greenfield 多對多匹配 scenario explorer."""

from __future__ import annotations

from pydantic import BaseModel

from app.schemas.optimization import (
    OptCustomerSummary,
    OptCustomerTarget,
    OptFarmSummary,
)


class ScenarioAllocationOut(BaseModel):
    wind_farm_id: int
    customer_id: int
    allocated_mwh: float
    margin_per_kwh: float
    has_contract: bool


class ScenarioResult(BaseModel):
    period: str
    solver_status: str
    objective_gross_margin_ntd: float
    assumed_transfer_price_per_kwh: float
    farm_ids: list[int]
    customer_ids: list[int]
    allocations: list[ScenarioAllocationOut]
    customer_targets: list[OptCustomerTarget]
    customer_summaries: list[OptCustomerSummary]
    farm_summaries: list[OptFarmSummary]
