"""Domain models for the Energy Matching Platform.

情境：台灣企業綠電交易 (Corporate PPA / CPPA)。
- 風力發電案場 (WindFarm) 產出綠電。
- 企業 (Company) 有年用電量與 RE 目標 (RE100 承諾)。
- 綠電合約 (Contract) 綁定「企業 <-> 案場」，以發電量比例或固定電量約定轉供。

所有電量單位一律使用 MWh (百萬瓦時)，比例使用 0..1 的小數。
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class AllocationType(str, Enum):
    """綠電合約的分配方式。"""

    RATIO = "ratio"  # 依案場年發電量的固定比例 (value 為 0..1)
    VOLUME = "volume"  # 固定年電量 (value 為 MWh)


class WindFarm(BaseModel):
    """風力發電案場。"""

    id: str
    name: str
    location: str = Field(..., description="案場所在縣市/海域")
    capacity_mw: float = Field(..., gt=0, description="裝置容量 (MW)")
    annual_generation_mwh: float = Field(
        ..., gt=0, description="年發電量 (MWh)"
    )

    @property
    def capacity_factor(self) -> float:
        """容量因數 = 年發電量 / (裝置容量 * 8760h)。"""
        return self.annual_generation_mwh / (self.capacity_mw * 8760.0)


class Company(BaseModel):
    """購買綠電的企業用電戶。"""

    id: str
    name: str
    industry: str
    annual_consumption_mwh: float = Field(
        ..., gt=0, description="年用電量 (MWh)"
    )
    re_target_ratio: float = Field(
        ..., ge=0, le=1, description="RE 目標佔比 (0..1)，例如 RE100 = 1.0"
    )

    @property
    def re_target_mwh(self) -> float:
        """達成 RE 目標所需的綠電量 (MWh)。"""
        return self.annual_consumption_mwh * self.re_target_ratio


class Contract(BaseModel):
    """企業綠電合約 (CPPA)：將某案場的產出轉供給某企業。"""

    id: str
    company_id: str
    wind_farm_id: str
    allocation_type: AllocationType
    value: float = Field(
        ..., gt=0, description="ratio: 0..1 的比例；volume: 年電量 MWh"
    )
    price_per_kwh: float = Field(..., gt=0, description="躉購/轉供費率 (元/kWh)")
    start_year: int = Field(..., ge=2000, le=2100)

    @field_validator("value")
    @classmethod
    def _check_ratio_range(cls, v: float, info) -> float:
        alloc = info.data.get("allocation_type")
        if alloc == AllocationType.RATIO and not (0 < v <= 1):
            raise ValueError("ratio 合約的 value 必須介於 0 與 1 之間")
        return v


class Dataset(BaseModel):
    """一次媒合所需的完整輸入資料。"""

    wind_farms: list[WindFarm]
    companies: list[Company]
    contracts: list[Contract]


# ---- 結果模型 ----------------------------------------------------------------


class ContractAllocation(BaseModel):
    """單一合約的分配結果。"""

    contract_id: str
    company_id: str
    wind_farm_id: str
    requested_mwh: float = Field(..., description="合約需求電量")
    allocated_mwh: float = Field(..., description="實際分配電量")
    curtailed: bool = Field(
        ..., description="案場超額認購時是否被等比例削減"
    )


class CompanyResult(BaseModel):
    """單一企業的媒合與 RE 目標分析。"""

    company_id: str
    name: str
    annual_consumption_mwh: float
    re_target_ratio: float
    re_target_mwh: float
    allocated_mwh: float
    coverage_ratio: float = Field(..., description="綠電覆蓋率 = 分配量 / 用電量")
    target_gap_mwh: float = Field(..., description="距離 RE 目標的缺口 (>=0)")
    target_met: bool


class WindFarmResult(BaseModel):
    """單一案場的利用情形。"""

    wind_farm_id: str
    name: str
    annual_generation_mwh: float
    allocated_mwh: float
    surplus_mwh: float = Field(..., description="未售出的剩餘綠電")
    utilization_ratio: float
    oversubscribed: bool


class PlatformSummary(BaseModel):
    """平台整體統計。"""

    total_generation_mwh: float
    total_allocated_mwh: float
    total_surplus_mwh: float
    utilization_ratio: float
    total_target_gap_mwh: float
    companies_meeting_target: int
    company_count: int


class MatchingResult(BaseModel):
    """完整媒合結果。"""

    allocations: list[ContractAllocation]
    company_results: list[CompanyResult]
    wind_farm_results: list[WindFarmResult]
    summary: PlatformSummary
