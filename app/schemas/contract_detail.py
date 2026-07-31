"""合約詳情（商務視角）回應 schema。

一紙合約在某一年的逐月履約與雙面帳。金額欄位在合約未設售電價時全為 None——
用躉售價代入讓毛利變成 0 會是個看起來合理但不真實的數字。
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel


class ContractMonth(BaseModel):
    period: str  # "2024-03"
    month: int  # 1–12
    in_force: bool  # False = 未生效／已到期／狀態非 active
    skip_reason: str | None  # 引擎原文,僅 in_force=False 時有值

    # 履約
    cap_mwh: float | None  # 本月合約上限（None = 未設上限,或該月未生效）
    cap_source: str  # volume | percentage | both | none
    allocated_mwh: float
    utilization_percent: float | None  # allocated/cap；cap 為 None 或 0 時亦為 None
    min_offtake_mwh: float  # take-or-pay 門檻（0 = 無此條款／非量制／未生效）
    shortfall_mwh: float  # max(0, min_offtake_mwh − allocated_mwh)
    binding: list[str]
    binding_primary: str  # farm_supply|customer_demand|contract_cap|none|not_in_force
    reason: str  # 引擎原文,可稽核
    headroom: bool
    farm_unallocated_mwh: float
    customer_unmet_mwh: float

    # 金額（has_price=False 時全為 None）
    price_per_kwh: float | None  # CPI 調整後
    energy_cost: float | None
    wheeling_fee: float | None
    take_or_pay_charge: float | None
    buyer_payable: float | None
    seller_receivable: float | None
    retailer_margin: float | None


class ContractYearTotals(BaseModel):
    months_in_force: int
    allocated_mwh: float
    cap_mwh: float | None  # 生效月份的上限加總；任一生效月未設上限則為 None
    utilization_percent: float | None
    min_offtake_mwh: float
    shortfall_mwh: float
    shortfall_months: int
    binding_counts: dict[str, int]  # 12 個月的 binding_primary 分佈,總和恆為 12
    headroom_months: int
    energy_cost: float | None
    wheeling_fee: float | None
    take_or_pay_charge: float | None
    buyer_payable: float | None
    seller_receivable: float | None
    retailer_margin: float | None
    margin_percent: float | None  # 毛利／買方應付 × 100；買方應付為 0 時為 None
    carbon_avoided_tco2e: float


class ContractDetail(BaseModel):
    contract_id: int
    contract_number: str
    year: int
    status: str
    priority: int
    start_date: date
    end_date: date
    wind_farm_id: int
    wind_farm_code: str
    wind_farm_name: str
    customer_id: int
    customer_code: str
    company_name: str

    # 條款
    contracted_energy_mwh: float | None
    contracted_percentage: float | None
    monthly_shares: list[float] | None  # 原始權重
    monthly_share_fractions: list[float] | None  # 正規化後的 12 個占比,供繪圖
    min_offtake_percent: float | None
    price_escalation_percent: float | None
    price_base_year: int | None
    base_price_per_kwh: float | None
    higher_priority_sibling_count: int  # 同案場、該年度有效、優先序更高的合約數

    # 計價前提（全部外顯,不藏預設值）
    has_price: bool
    used_default_feed_in: bool
    feed_in_price_per_kwh: float
    wheeling_fee_per_kwh: float
    grid_emission_factor_kg_per_kwh: float

    has_period_data: bool  # 該年度是否有任何發電或用電資料
    months: list[ContractMonth]  # 恆為 12 筆
    totals: ContractYearTotals
