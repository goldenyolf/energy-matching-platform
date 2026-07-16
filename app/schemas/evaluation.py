# app/schemas/evaluation.py
"""Sales-evaluation response schema (seller + buyer economics)."""

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


class EvaluationResult(BaseModel):
    customer_id: int
    customer_code: str
    company_name: str
    start: str
    end: str
    used_default_feed_in_price: bool
    seller: SellerSide
    buyer: BuyerSide
