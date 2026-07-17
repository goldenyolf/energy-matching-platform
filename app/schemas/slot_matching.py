"""Response schema for the time-slot matching endpoint (P4a)."""

from __future__ import annotations

from pydantic import BaseModel


class SlotAllocationOut(BaseModel):
    contract_id: int
    contract_number: str
    wind_farm_id: int
    customer_id: int
    slot: str
    allocated_mwh: float
    reason: str


class CustomerSummaryOut(BaseModel):
    customer_id: int
    consumption_mwh: float
    allocated_mwh: float
    achieved_re_percent: float


class FarmSummaryOut(BaseModel):
    wind_farm_id: int
    generated_mwh: float
    allocated_mwh: float
    unallocated_mwh: float


class SlotBreakdown(BaseModel):
    slot: str
    grey_price_per_kwh: float
    customer_summaries: list[CustomerSummaryOut]
    farm_summaries: list[FarmSummaryOut]


class BuyerSide(BaseModel):
    re_percent: float
    avg_price_per_kwh: float
    added_cost: float


class SlotMatchingResult(BaseModel):
    period: str
    season: str
    allocations: list[SlotAllocationOut]
    customer_summaries: list[CustomerSummaryOut]
    farm_summaries: list[FarmSummaryOut]
    slot_breakdown: list[SlotBreakdown]
    seller_gross_margin_ntd: float
    buyer: BuyerSide
