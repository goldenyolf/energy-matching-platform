"""Unified per-customer optimization evaluation schema (v1.1).

All fields derive from a single P3 MILP optimizer run for the target customer,
so the seller/buyer economics, per-farm allocation, and time-slot breakdown are
mutually consistent.
"""

from __future__ import annotations

from pydantic import BaseModel


class SellerSide(BaseModel):
    procurement_cost: float
    sales_revenue: float
    gross_profit: float
    gross_margin_percent: float


class BuyerSide(BaseModel):
    total_consumption_mwh: float
    green_mwh: float
    grey_mwh: float
    re_percent: float
    avg_price_per_kwh: float
    added_cost: float


class FarmAllocationOut(BaseModel):
    wind_farm_id: int
    wind_farm_code: str
    wind_farm_name: str
    allocated_mwh: float
    share_percent: float
    contract_number: str
    reason: str


class SlotRowOut(BaseModel):
    slot: str
    grey_price_per_kwh: float
    consumption_mwh: float
    allocated_mwh: float
    re_percent: float


class CustomerOptimizationResult(BaseModel):
    period: str
    season: str
    solver_status: str
    customer_id: int
    customer_code: str
    company_name: str
    re_target_percent: float
    transfer_price_used: float | None
    min_sites_per_customer: int
    min_site_allocation_percent: float
    used_default_feed_in_price: bool
    seller: SellerSide
    buyer: BuyerSide
    allocations: list[FarmAllocationOut]
    slot_breakdown: list[SlotRowOut]
    time_mismatch_surplus_mwh: float
