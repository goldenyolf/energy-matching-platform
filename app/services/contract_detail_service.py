"""合約詳情（商務視角）：把 12 次月度媒合的結果攤成一紙合約的履約與帳。

引擎（``app/matching/engine.py``）不改,本模組唯讀使用它的輸出。
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.matching import MatchingOutcome
from app.matching.contract_terms import (
    effective_price,
    min_offtake_mwh,
    monthly_share,
    monthly_volume_cap,
)
from app.models import ConsumptionData, Contract, Customer, GenerationData, WindFarm
from app.models.enums import ContractStatus
from app.schemas.contract_detail import (
    ContractDetail,
    ContractMonth,
    ContractYearTotals,
)
from app.services import contracts as contract_svc
from app.services.matching_service import compute_outcome

EPS = 1e-9
_KWH = 1000.0


@dataclass(frozen=True)
class _Pricing:
    """一年份的計價前提。售電價經 CPI 調整後全年同一個值。"""

    price_per_kwh: float | None  # None = 合約未設售電價
    feed_in_per_kwh: float
    wheeling_per_kwh: float


# 引擎 reason 字串裡的用語 → 本模組的約束代碼。
# 前三個來自有分配的情況,後三個來自 ``no allocation: …``——零分配時引擎也講了
# 原因,對應回去比一律歸類成「無」更有資訊。
_BINDING_WORDS = {
    "wind farm supply": "farm_supply",
    "customer demand": "customer_demand",
    "contract cap": "contract_cap",
    "wind farm has no remaining generation": "farm_supply",
    "customer consumption already fully covered": "customer_demand",
    "contract cap is zero": "contract_cap",
}

# 同時綁定多個約束時只挑一個上色與統計。案場供給用盡是最硬的限制——
# 調高合約上限也拿不到更多電,所以它排最前面;合約上限最軟,排最後。
_PRECEDENCE = ("farm_supply", "customer_demand", "contract_cap")


def classify_binding(reason: str) -> tuple[list[str], str]:
    """把引擎的 reason 字串拆成約束代碼清單與單一主約束。

    回傳的清單依 ``_PRECEDENCE`` 排序（穩定,不受 reason 字序影響）;
    認不出任何約束時回 ``([], "none")``。
    """
    found = {code for word, code in _BINDING_WORDS.items() if word in reason}
    ordered = [c for c in _PRECEDENCE if c in found]
    return (ordered, ordered[0]) if ordered else ([], "none")


def has_headroom(
    binding_primary: str, farm_unallocated_mwh: float, customer_unmet_mwh: float
) -> bool:
    """這個月有沒有「加購空間」。

    三個條件缺一不可：被合約上限卡住、案場還有餘電、客戶還有沒被滿足的用電。
    少了後兩者任一,「調高上限就能多拿」這句話就是假的——所以不能只看綁定約束。
    """
    return (
        binding_primary == "contract_cap"
        and farm_unallocated_mwh > EPS
        and customer_unmet_mwh > EPS
    )


def _cap_source(contract: Contract) -> str:
    """這紙合約設了哪些上限——12 個月皆同,與當月有沒有生效無關。"""
    has_volume = contract.contracted_energy_mwh is not None
    has_percent = contract.contracted_percentage is not None
    if has_volume and has_percent:
        return "both"
    if has_volume:
        return "volume"
    if has_percent:
        return "percentage"
    return "none"


def _has_period_data(db: Session, year: int) -> bool:
    """該年度有沒有任何發電或用電量測。沒有的話整頁的圖都不該畫。"""
    start, end = date(year, 1, 1), date(year, 12, 31)
    gen = db.scalar(
        select(func.count())
        .select_from(GenerationData)
        .where(GenerationData.period_start >= start, GenerationData.period_start <= end)
    )
    con = db.scalar(
        select(func.count())
        .select_from(ConsumptionData)
        .where(
            ConsumptionData.period_start >= start, ConsumptionData.period_start <= end
        )
    )
    return bool(gen) or bool(con)


def _higher_priority_siblings(db: Session, contract: Contract, year: int) -> int:
    """同案場、該年度內任一時點有效、且優先序嚴格更高的合約數。

    畫面用它決定要不要說「本合約被插隊」——本合約已是最高優先序時這句話是錯的。
    """
    start, end = date(year, 1, 1), date(year, 12, 31)
    return (
        db.scalar(
            select(func.count())
            .select_from(Contract)
            .where(
                Contract.wind_farm_id == contract.wind_farm_id,
                Contract.id != contract.id,
                Contract.status == ContractStatus.ACTIVE,
                Contract.priority < contract.priority,
                Contract.start_date <= end,
                Contract.end_date >= start,
            )
        )
        or 0
    )


def _month_context(outcome: MatchingOutcome, contract: Contract) -> tuple[float, float]:
    """本月案場還剩多少未分配、客戶還有多少沒被滿足——加購空間判定的兩個前提。"""
    farm = next(
        (f for f in outcome.farm_summaries if f.farm_id == contract.wind_farm_id), None
    )
    cust = next(
        (
            c
            for c in outcome.customer_summaries
            if c.customer_id == contract.customer_id
        ),
        None,
    )
    farm_left = max(0.0, farm.unallocated_mwh) if farm else 0.0
    cust_unmet = max(0.0, cust.consumption_mwh - cust.allocated_mwh) if cust else 0.0
    return farm_left, cust_unmet


def _not_in_force_month(
    period: str,
    month: int,
    reason: str,
    cap_source: str,
    farm_left: float,
    cust_unmet: float,
    pricing: _Pricing,
) -> ContractMonth:
    """未生效／已到期的月份。分配是 None 語意,不是 0——這格講錯整頁就毀了。"""
    return ContractMonth(
        period=period,
        month=month,
        in_force=False,
        skip_reason=reason,
        cap_mwh=None,
        cap_source=cap_source,
        allocated_mwh=0.0,
        utilization_percent=None,
        min_offtake_mwh=0.0,
        shortfall_mwh=0.0,
        binding=[],
        binding_primary="not_in_force",
        reason=reason,
        headroom=False,
        farm_unallocated_mwh=round(farm_left, 6),
        customer_unmet_mwh=round(cust_unmet, 6),
        **_money(pricing, 0.0, 0.0),
    )


def _money(
    pricing: _Pricing, allocated_mwh: float, shortfall_mwh: float
) -> dict[str, float | None]:
    """單月三方金額。公式沿用 ``settlement_service``,只是把範圍縮到這紙合約。

    所有費率都是 per-kWh,保證量門檻也是合約層級的——因此不需要任何
    「這紙合約該分攤客戶多少費用」之類的分攤假設。
    """
    if pricing.price_per_kwh is None:
        return {
            "price_per_kwh": None,
            "energy_cost": None,
            "wheeling_fee": None,
            "take_or_pay_charge": None,
            "buyer_payable": None,
            "seller_receivable": None,
            "retailer_margin": None,
        }
    kwh = allocated_mwh * _KWH
    energy_cost = kwh * pricing.price_per_kwh
    wheeling_fee = kwh * pricing.wheeling_per_kwh
    top_charge = shortfall_mwh * _KWH * pricing.price_per_kwh
    seller = kwh * pricing.feed_in_per_kwh
    return {
        "price_per_kwh": round(pricing.price_per_kwh, 6),
        "energy_cost": round(energy_cost, 2),
        "wheeling_fee": round(wheeling_fee, 2),
        "take_or_pay_charge": round(top_charge, 2),
        "buyer_payable": round(energy_cost + wheeling_fee + top_charge, 2),
        "seller_receivable": round(seller, 2),
        "retailer_margin": round(energy_cost - seller - wheeling_fee + top_charge, 2),
    }


def _build_months(
    db: Session, contract: Contract, year: int, cap_source: str, pricing: _Pricing
) -> list[ContractMonth]:
    months: list[ContractMonth] = []
    for m in range(1, 13):
        period = f"{year}-{m:02d}"
        outcome = compute_outcome(db, period)
        farm_left, cust_unmet = _month_context(outcome, contract)
        alloc = next(
            (a for a in outcome.allocations if a.contract_id == contract.id), None
        )
        if alloc is None:
            skipped = next(
                (s for s in outcome.skipped if s.contract_id == contract.id), None
            )
            months.append(
                _not_in_force_month(
                    period,
                    m,
                    skipped.reason if skipped else "contract not in this period",
                    cap_source,
                    farm_left,
                    cust_unmet,
                    pricing,
                )
            )
            continue

        cap = alloc.contract_limit_mwh
        binding, primary = classify_binding(alloc.reason)
        floor = min_offtake_mwh(
            monthly_volume_cap(
                contract.contracted_energy_mwh, contract.monthly_shares, m
            ),
            contract.min_offtake_percent,
        )
        months.append(
            ContractMonth(
                period=period,
                month=m,
                in_force=True,
                skip_reason=None,
                cap_mwh=None if cap is None else round(cap, 6),
                cap_source=cap_source,
                allocated_mwh=round(alloc.allocated_mwh, 6),
                utilization_percent=(
                    round(alloc.allocated_mwh / cap * 100.0, 6) if cap else None
                ),
                min_offtake_mwh=round(floor, 6),
                shortfall_mwh=round(max(0.0, floor - alloc.allocated_mwh), 6),
                binding=binding,
                binding_primary=primary,
                reason=alloc.reason,
                headroom=has_headroom(primary, farm_left, cust_unmet),
                farm_unallocated_mwh=round(farm_left, 6),
                customer_unmet_mwh=round(cust_unmet, 6),
                **_money(
                    pricing, alloc.allocated_mwh, max(0.0, floor - alloc.allocated_mwh)
                ),
            )
        )
    return months


def _build_totals(
    months: list[ContractMonth], factor: float, has_price: bool
) -> ContractYearTotals:
    in_force = [m for m in months if m.in_force]
    allocated = sum(m.allocated_mwh for m in in_force)
    caps = [m.cap_mwh for m in in_force]
    total_cap = (
        sum(c for c in caps if c is not None)
        if caps and all(c is not None for c in caps)
        else None
    )

    def total(field: str) -> float | None:
        if not has_price:
            return None
        return round(sum(getattr(m, field) or 0.0 for m in months), 2)

    buyer = total("buyer_payable")
    margin = total("retailer_margin")
    return ContractYearTotals(
        months_in_force=len(in_force),
        allocated_mwh=round(allocated, 6),
        cap_mwh=None if total_cap is None else round(total_cap, 6),
        utilization_percent=(
            round(allocated / total_cap * 100.0, 6) if total_cap else None
        ),
        min_offtake_mwh=round(sum(m.min_offtake_mwh for m in in_force), 6),
        shortfall_mwh=round(sum(m.shortfall_mwh for m in in_force), 6),
        shortfall_months=sum(1 for m in in_force if m.shortfall_mwh > EPS),
        binding_counts=dict(Counter(m.binding_primary for m in months)),
        headroom_months=sum(1 for m in months if m.headroom),
        energy_cost=total("energy_cost"),
        wheeling_fee=total("wheeling_fee"),
        take_or_pay_charge=total("take_or_pay_charge"),
        buyer_payable=buyer,
        seller_receivable=total("seller_receivable"),
        retailer_margin=margin,
        margin_percent=(
            round(margin / buyer * 100.0, 6) if buyer and margin is not None else None
        ),
        carbon_avoided_tco2e=round(allocated * factor, 6),
    )


def compute_contract_detail(db: Session, contract_id: int, year: int) -> ContractDetail:
    """一紙合約在 ``year`` 這一年的逐月履約與雙面帳。

    以 ``match_period``（合約優先序）為基準,不是 ``optimize_period``——履約講的是
    「依約該拿到什麼」,不是「最佳化後會拿到什麼」。因此本頁金額與轉供結算單頁
    會有落差,頁面上會註明。
    """
    contract = contract_svc.get(db, contract_id)
    farm = db.get(WindFarm, contract.wind_farm_id)
    customer = db.get(Customer, contract.customer_id)
    cap_source = _cap_source(contract)

    feed_in = farm.feed_in_price_per_kwh if farm else None
    used_default_feed_in = feed_in is None
    if feed_in is None:
        feed_in = settings.default_feed_in_price_per_kwh

    pricing = _Pricing(
        price_per_kwh=(
            effective_price(
                contract.price_per_kwh,
                contract.price_escalation_percent,
                contract.price_base_year,
                year,
            )
            if contract.price_per_kwh is not None
            else None
        ),
        feed_in_per_kwh=feed_in,
        wheeling_per_kwh=settings.wheeling_fee_per_kwh,
    )
    months = _build_months(db, contract, year, cap_source, pricing)
    totals = _build_totals(
        months,
        settings.grid_emission_factor_kg_per_kwh,
        contract.price_per_kwh is not None,
    )

    shares = contract.monthly_shares
    return ContractDetail(
        contract_id=contract.id,
        contract_number=contract.contract_number,
        year=year,
        status=contract.status.value,
        priority=contract.priority,
        start_date=contract.start_date,
        end_date=contract.end_date,
        wind_farm_id=contract.wind_farm_id,
        wind_farm_code=farm.code if farm else str(contract.wind_farm_id),
        wind_farm_name=(farm.name if farm else "") or "",
        customer_id=contract.customer_id,
        customer_code=customer.code if customer else str(contract.customer_id),
        company_name=(customer.company_name if customer else "") or "",
        contracted_energy_mwh=contract.contracted_energy_mwh,
        contracted_percentage=contract.contracted_percentage,
        monthly_shares=shares,
        monthly_share_fractions=(
            [monthly_share(shares, m) for m in range(1, 13)] if shares else None
        ),
        min_offtake_percent=contract.min_offtake_percent,
        price_escalation_percent=contract.price_escalation_percent,
        price_base_year=contract.price_base_year,
        base_price_per_kwh=contract.price_per_kwh,
        higher_priority_sibling_count=_higher_priority_siblings(db, contract, year),
        has_price=contract.price_per_kwh is not None,
        used_default_feed_in=used_default_feed_in,
        feed_in_price_per_kwh=feed_in,
        wheeling_fee_per_kwh=settings.wheeling_fee_per_kwh,
        grid_emission_factor_kg_per_kwh=settings.grid_emission_factor_kg_per_kwh,
        has_period_data=_has_period_data(db, year),
        months=months,
        totals=totals,
    )
