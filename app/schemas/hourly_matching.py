"""Response schema for the hourly (24/7 CFE) matching endpoint (B7)."""

from __future__ import annotations

from pydantic import BaseModel


class HourlyCustomerOut(BaseModel):
    customer_id: int
    name: str
    industry: str | None
    consumption_mwh: float
    matched_mwh: float
    cfe_percent: float  # 逐時時間匹配率
    paper_re_percent: float  # 帳面月淨額（對照）
    matched_by_hour: list[float]
    shortfall_by_hour: list[float]


class HourlyFarmOut(BaseModel):
    wind_farm_id: int
    name: str
    generated_mwh: float
    matched_mwh: float
    surplus_mwh: float


class HeatmapOut(BaseModel):
    days: list[str]  # ISO date per row
    values: list[list[float]]  # values[day][hour] = CFE%


class HourlyMatchingResult(BaseModel):
    period: str
    source: str  # "interval"（真實/模擬逐日 15 分鐘）| "modeled"（典型日型建模）
    modeled: bool  # True = 典型日型建模（半模擬），非實測
    note: str
    hours: int
    days: int  # 熱力圖天數（interval 模式），modeled 模式為 1
    heatmap: HeatmapOut | None
    cfe_percent: float  # 系統逐時 CFE%
    paper_re_percent: float  # 系統帳面 RE%（月淨額上限）
    total_consumption_mwh: float
    total_matched_mwh: float
    total_surplus_mwh: float
    total_shortfall_mwh: float
    generation_by_hour: list[float]
    consumption_by_hour: list[float]
    matched_by_hour: list[float]
    surplus_by_hour: list[float]
    shortfall_by_hour: list[float]
    customers: list[HourlyCustomerOut]
    farms: list[HourlyFarmOut]
