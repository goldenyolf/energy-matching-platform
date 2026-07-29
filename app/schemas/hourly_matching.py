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
    # 儲能（B5）：加電池之前的同一位客戶 CFE，與電池帶來的增益。
    no_storage_cfe_percent: float | None = None
    storage_uplift_pt: float | None = None
    # 儲能（B5）：這位客戶自己的電池（如果有）逐時放電與 SOC。沒有電池時為 None。
    # 與系統級同一套摺算方式：放電是流量 → reduce24 加總；SOC 是存量 →
    # reduce24 加總後除以天數,曲線才會停在單一電池的容量尺度。
    discharged_by_hour: list[float] | None = None
    soc_by_hour: list[float] | None = None


class HourlyFarmOut(BaseModel):
    """發電只會落在三個互斥的桶：``generated = matched + charged + surplus``。"""

    wind_farm_id: int
    name: str
    generated_mwh: float
    matched_mwh: float  # 同一小時直接送到客戶（不含充進電池的量）
    surplus_mwh: float  # 外溢：沒人用,也沒存進電池
    # 儲能（B5）：被充進電池的量。沒有電池時為 None。
    charged_mwh: float | None = None


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
    # 儲能（B5）：cfe_percent 已含儲能；no_storage 是加電池前的對照。
    # 三段式讀數＝wind_only → no_storage → cfe_percent。
    no_storage_cfe_percent: float | None = None
    storage_uplift_pt: float | None = None
    soc_by_hour: list[float] | None = None  # 系統合計 SOC（MWh）
    discharged_by_hour: list[float] | None = None
    charged_by_hour: list[float] | None = None
    # 加了儲能之後的能量帳（見 app/matching/storage.py 的 docstring）：
    #   generated = matched（直供）+ charged（充進電池）+ surplus（外溢）
    #   charged   = discharged（真的送出去）+ 往返損耗 + 期末殘留
    # 所以 total_charged − total_discharged 就是「進得去、出不來」的那一段——
    # 它誰也沒用到,既不算 matched,也不會被 total_surplus 吸收掉。
    total_charged_mwh: float | None = None
    total_discharged_mwh: float | None = None
    total_consumption_mwh: float
    total_matched_mwh: float  # 案場直供 + 電池送出
    total_surplus_mwh: float  # 外溢：沒人用,也沒存進電池
    total_shortfall_mwh: float
    generation_by_hour: list[float]
    consumption_by_hour: list[float]
    matched_by_hour: list[float]
    surplus_by_hour: list[float]
    shortfall_by_hour: list[float]
    customers: list[HourlyCustomerOut]
    farms: list[HourlyFarmOut]
