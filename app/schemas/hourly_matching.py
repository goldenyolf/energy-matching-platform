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
    # 風光互補（B4），同 HourlyMatchingResult：只留風電資產重跑一次的對照。
    # 系統級增益會被沒簽光電的大客戶稀釋，簽了的那一家才看得出效果。
    wind_only_cfe_percent: float | None = None
    uplift_pt: float | None = None


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
    cfe_percent: float  # 系統逐時 CFE%（風光合計）
    paper_re_percent: float  # 系統帳面 RE%（月淨額上限）
    # 風光互補（B4）：同一批負載、只留風電資產與其合約重跑一次的對照基準。
    # 沒有光電案場時就沒有對照組，兩者皆為 None。
    wind_only_cfe_percent: float | None = None
    uplift_pt: float | None = None  # cfe_percent − wind_only_cfe_percent（百分點）
    # generation_by_hour 之中屬於太陽能的那一層（前端「風 + 光」堆疊用；風＝總 − 光）
    solar_generation_by_hour: list[float] | None = None
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
