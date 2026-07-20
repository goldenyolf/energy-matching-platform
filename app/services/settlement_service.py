"""Transfer settlement bill (轉供結算單) — projection of the matching result.

Reuses ``compute_customer_optimization`` (no new matching); adds a Taipower
wheeling fee and a carbon-reduction figure, and lays the result out per TOU slot
for a formal two-sided bill.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.config import settings
from app.schemas.settlement import (
    SettlementParty,
    SettlementResult,
    SettlementSlotRow,
    SettlementTotals,
)
from app.services.customer_optimization_service import (
    CustomerOptimizeOptions,
    compute_customer_optimization,
)

_KWH = 1000.0


@dataclass(frozen=True)
class SettlementOptions:
    transfer_price_per_kwh: float | None = None
    wheeling_fee_per_kwh: float | None = None


def compute_settlement(
    db: Session, customer_id: int, period: str, opts: SettlementOptions
) -> SettlementResult:
    wheeling = (
        settings.wheeling_fee_per_kwh
        if opts.wheeling_fee_per_kwh is None
        else opts.wheeling_fee_per_kwh
    )
    factor = settings.grid_emission_factor_kg_per_kwh

    co = compute_customer_optimization(
        db,
        customer_id,
        period,
        CustomerOptimizeOptions(
            min_sites_per_customer=settings.optimize_min_sites_per_customer,
            min_site_allocation_percent=settings.optimize_min_site_allocation_percent,
            re_target_percent=None,
            transfer_price_per_kwh=opts.transfer_price_per_kwh,
        ),
    )

    green_total = co.buyer.green_mwh
    # single transfer price: prefer the value the optimizer used; else derive
    price = co.transfer_price_used
    if price is None:
        price = (
            co.seller.sales_revenue / (green_total * _KWH) if green_total > 0 else 0.0
        )

    slots: list[SettlementSlotRow] = []
    grey_total = 0.0
    for s in co.slot_breakdown:
        green_mwh = s.allocated_mwh
        grey_mwh = max(0.0, s.consumption_mwh - s.allocated_mwh)
        grey_total += grey_mwh
        slots.append(
            SettlementSlotRow(
                slot=s.slot,
                green_mwh=round(green_mwh, 3),
                transfer_price_per_kwh=round(price, 4),
                green_cost=round(green_mwh * _KWH * price, 2),
                grey_mwh=round(grey_mwh, 3),
                grey_price_per_kwh=s.grey_price_per_kwh,
                grey_cost=round(grey_mwh * _KWH * s.grey_price_per_kwh, 2),
            )
        )

    green_transfer_cost = co.seller.sales_revenue
    wheeling_fee = green_total * _KWH * wheeling
    grey_cost = sum(row.grey_cost for row in slots)
    customer_payable = green_transfer_cost + wheeling_fee
    farm_receivable = co.seller.procurement_cost
    retailer_margin = green_transfer_cost - farm_receivable - wheeling_fee
    margin_pct = (
        retailer_margin / customer_payable * 100.0 if customer_payable > 0 else 0.0
    )
    carbon = green_total * factor  # green_kWh × kg/kWh ÷ 1000 = green_mwh × factor

    farms = [
        SettlementParty(
            wind_farm_code=a.wind_farm_code,
            wind_farm_name=a.wind_farm_name,
            allocated_mwh=round(a.allocated_mwh, 3),
            contract_number=a.contract_number,
        )
        for a in co.allocations
    ]

    return SettlementResult(
        period=co.period,
        season=co.season,
        solver_status=co.solver_status,
        customer_id=co.customer_id,
        customer_code=co.customer_code,
        company_name=co.company_name,
        transfer_price_per_kwh=round(price, 4),
        wheeling_fee_per_kwh=wheeling,
        grid_emission_factor_kg_per_kwh=factor,
        farms=farms,
        slots=slots,
        totals=SettlementTotals(
            green_mwh=round(green_total, 3),
            grey_mwh=round(grey_total, 3),
            green_transfer_cost=round(green_transfer_cost, 2),
            wheeling_fee=round(wheeling_fee, 2),
            grey_cost=round(grey_cost, 2),
            customer_payable=round(customer_payable, 2),
            farm_receivable=round(farm_receivable, 2),
            retailer_margin=round(retailer_margin, 2),
            retailer_margin_percent=round(margin_pct, 4),
            carbon_avoided_tco2e=round(carbon, 2),
        ),
    )
