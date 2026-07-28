"""Investment analysis: per-farm and portfolio ROI / payback (compute-only).

For each wind farm: CAPEX = capacity × capex_per_mw; annual revenue = annual
generation sold at the farm's feed-in (躉售) price; annual O&M = CAPEX × rate;
annual net = revenue − O&M; ROI = net / CAPEX; payback = CAPEX / net. Annual
generation is the sum of the farm's generation rows (the demo data is one year).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import GenerationData, WindFarm
from app.schemas.investment import (
    FarmInvestment,
    InvestmentResult,
    InvestmentTotal,
)

_KWH = 1000.0
_HOURS_PER_YEAR = 8760.0


def expected_annual_mwh(capacity_mw: float, cf_percent: float | None) -> float | None:
    """Expected annual generation from a capacity factor (None if no CF)."""
    if cf_percent is None:
        return None
    return capacity_mw * _HOURS_PER_YEAR * cf_percent / 100.0


def compute_investment(
    db: Session,
    capex_per_mw: float,
    om_rate_percent: float,
    scenario: str = "actual",
) -> InvestmentResult:
    """ROI/payback per farm. ``scenario`` picks the annual generation basis:
    ``actual`` (measured), ``p50`` (capacity × 8760 × CF), or ``p90`` (the
    conservative CF). p50/p90 fall back to actual for farms with no CF set."""
    default_feed = settings.default_feed_in_price_per_kwh

    gen_total: dict[int, float] = {}
    for g in db.execute(select(GenerationData)).scalars():
        gen_total[g.wind_farm_id] = (
            gen_total.get(g.wind_farm_id, 0.0) + g.generated_energy_mwh
        )

    farms: list[FarmInvestment] = []
    t_cap = t_gen = t_rev = t_capex = t_om = t_net = 0.0
    for f in db.execute(select(WindFarm).order_by(WindFarm.id)).scalars():
        cap_mw = f.installed_capacity_mw
        actual_gen = gen_total.get(f.id, 0.0)
        if scenario == "p50":
            annual_gen = expected_annual_mwh(cap_mw, f.capacity_factor_percent)
        elif scenario == "p90":
            annual_gen = expected_annual_mwh(cap_mw, f.p90_capacity_factor_percent)
        else:
            annual_gen = actual_gen
        if annual_gen is None:  # p50/p90 with no CF → fall back to measured
            annual_gen = actual_gen
        price = (
            f.feed_in_price_per_kwh
            if f.feed_in_price_per_kwh is not None
            else default_feed
        )
        revenue = annual_gen * _KWH * price
        capex = cap_mw * capex_per_mw
        om = capex * om_rate_percent / 100.0
        net = revenue - om
        roi = (net / capex * 100.0) if capex else 0.0
        payback = (capex / net) if net > 0 else None
        farms.append(
            FarmInvestment(
                wind_farm_id=f.id,
                code=f.code,
                name=f.name,
                capacity_mw=cap_mw,
                annual_generation_mwh=round(annual_gen, 3),
                selling_price_per_kwh=price,
                annual_revenue=round(revenue, 2),
                capex=round(capex, 2),
                annual_om=round(om, 2),
                annual_net=round(net, 2),
                roi_percent=round(roi, 4),
                payback_years=(round(payback, 2) if payback is not None else None),
                farm_type=f.farm_type,
                capacity_factor_percent=f.capacity_factor_percent,
            )
        )
        t_cap += cap_mw
        t_gen += annual_gen
        t_rev += revenue
        t_capex += capex
        t_om += om
        t_net += net

    total_roi = (t_net / t_capex * 100.0) if t_capex else 0.0
    total_payback = (t_capex / t_net) if t_net > 0 else None
    return InvestmentResult(
        capex_per_mw=capex_per_mw,
        om_rate_percent=om_rate_percent,
        scenario=scenario,
        farms=farms,
        total=InvestmentTotal(
            capacity_mw=round(t_cap, 3),
            annual_generation_mwh=round(t_gen, 3),
            annual_revenue=round(t_rev, 2),
            capex=round(t_capex, 2),
            annual_om=round(t_om, 2),
            annual_net=round(t_net, 2),
            roi_percent=round(total_roi, 4),
            payback_years=(
                round(total_payback, 2) if total_payback is not None else None
            ),
        ),
    )
