"""T-REC certificate ledger schema."""

from __future__ import annotations

from pydantic import BaseModel


class TrecBatchOut(BaseModel):
    id: int
    batch_no: str
    wind_farm_code: str
    wind_farm_name: str
    customer_code: str
    company_name: str
    period: str
    quantity_mwh: float
    status: str


class TrecSummary(BaseModel):
    total_batches: int
    total_quantity_mwh: float
    transferred_mwh: float
    retired_mwh: float
    transferred_batches: int
    retired_batches: int


class TrecLedger(BaseModel):
    period: str | None
    summary: TrecSummary
    batches: list[TrecBatchOut]
