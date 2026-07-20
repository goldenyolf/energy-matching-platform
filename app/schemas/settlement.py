"""Transfer settlement bill (轉供結算單) response schema."""

from __future__ import annotations

from pydantic import BaseModel


class SettlementSlotRow(BaseModel):
    slot: str
    green_mwh: float
    transfer_price_per_kwh: float
    green_cost: float
    grey_mwh: float
    grey_price_per_kwh: float
    grey_cost: float


class SettlementParty(BaseModel):
    wind_farm_code: str
    wind_farm_name: str
    allocated_mwh: float
    contract_number: str


class SettlementTotals(BaseModel):
    green_mwh: float
    grey_mwh: float
    green_transfer_cost: float
    wheeling_fee: float
    grey_cost: float
    customer_payable: float
    farm_receivable: float
    retailer_margin: float
    retailer_margin_percent: float
    carbon_avoided_tco2e: float


class SettlementResult(BaseModel):
    period: str
    season: str
    solver_status: str
    customer_id: int
    customer_code: str
    company_name: str
    transfer_price_per_kwh: float
    wheeling_fee_per_kwh: float
    grid_emission_factor_kg_per_kwh: float
    farms: list[SettlementParty]
    slots: list[SettlementSlotRow]
    totals: SettlementTotals
