"""Hourly (24/7 CFE) matching service: interval or modeled curves, match, score.

Compute-only (no persistence), mirroring the slot / optimize services. Two data
sources feed the same strict time-coincident engine (B7):

* **interval** (B6): when real/simulated 15-minute ``IntervalReading`` rows exist
  for the period, they are aggregated to hourly per (day, hour) and the engine
  runs over ``ndays × 24`` independent hour buckets. This yields a real hour×day
  CFE heatmap and a representative 24-hour profile summed over the month.
* **modeled** (A9): otherwise each period total is shaped into one typical 24-hour
  day. No heatmap.

Either way it reports the true CFE% against the "paper" monthly-netting figure
(the same totals matched in a single bucket — the upper bound CFE can't exceed).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.matching import contract_terms
from app.matching.hourly_matching import (
    HourlyContract,
    HourlyCustomer,
    HourlyFarm,
    match_hourly,
)
from app.matching.hourly_profile import (
    generation_shape,
    load_shape,
    technology,
    to_hourly,
)
from app.matching.interval_shape import (
    day_labels,
    days_in_period,
    heatmap_cfe,
    hour_of_day_sums,
)
from app.matching.storage import BatterySpec, apply_storage, with_storage
from app.models import (
    Battery,
    ConsumptionData,
    Contract,
    Customer,
    GenerationData,
    WindFarm,
)
from app.models.interval import KIND_GENERATION, IntervalReading
from app.schemas.hourly_matching import (
    HeatmapOut,
    HourlyCustomerOut,
    HourlyFarmOut,
    HourlyMatchingResult,
)
from app.services.matching_service import period_bounds

_MODELED_NOTE = (
    "逐時曲線為典型日型建模（風電夜強日弱、太陽能正午 bell、依產業別負載日型），"
    "Σ逐時＝原月量；接真實 interval 資料（A4）後原地替換。"
)
_INTERVAL_NOTE = (
    "逐時曲線來自逐日 15 分鐘 interval 資料（示範為模擬、含逐日變異），"
    "彙總到每小時匹配；解鎖時×日熱力圖。真實 AMI 以同一管線匯入即替換。"
)


def _sum_by(rows, key_attr: str, val_attr: str) -> dict[int, float]:
    totals: dict[int, float] = {}
    for row in rows:
        key = getattr(row, key_attr)
        totals[key] = totals.get(key, 0.0) + getattr(row, val_attr)
    return totals


def _load_interval(
    db: Session, start: date, end: date
) -> tuple[int, dict[int, list[float]], dict[int, list[float]]] | None:
    """Aggregate 15-minute rows into per-entity hourly arrays of length
    ``ndays*24`` (index = day*24 + hour). Returns None if there are no rows."""
    lo = datetime(start.year, start.month, start.day)
    hi = datetime(end.year, end.month, end.day) + timedelta(days=1)
    rows = list(
        db.execute(
            select(IntervalReading).where(
                IntervalReading.ts >= lo, IntervalReading.ts < hi
            )
        ).scalars()
    )
    if not rows:
        return None
    ndays = days_in_period(start, end)
    nb = ndays * 24
    gen: dict[int, list[float]] = {}
    con: dict[int, list[float]] = {}
    for r in rows:
        d = (r.ts.date() - start).days
        if d < 0 or d >= ndays:
            continue
        idx = d * 24 + r.ts.hour
        target = gen if r.kind == KIND_GENERATION else con
        target.setdefault(r.ref_id, [0.0] * nb)[idx] += r.energy_mwh
    return ndays, gen, con


def compute_hourly_outcome(
    db: Session, period: str, customer_id: int | None = None
) -> HourlyMatchingResult:
    start, end = period_bounds(period)
    month = int(period[5:7])

    gen_totals = _sum_by(
        db.execute(
            select(GenerationData).where(
                GenerationData.period_start >= start,
                GenerationData.period_start <= end,
            )
        ).scalars(),
        "wind_farm_id",
        "generated_energy_mwh",
    )
    con_totals = _sum_by(
        db.execute(
            select(ConsumptionData).where(
                ConsumptionData.period_start >= start,
                ConsumptionData.period_start <= end,
            )
        ).scalars(),
        "customer_id",
        "consumed_energy_mwh",
    )

    farm_rows = list(db.execute(select(WindFarm).order_by(WindFarm.id)).scalars())
    cust_rows = list(db.execute(select(Customer).order_by(Customer.id)).scalars())

    interval = _load_interval(db, start, end)
    if interval is not None:
        ndays, gen_series, con_series = interval
        nb = ndays * 24

        def farm_arr(f: WindFarm) -> list[float]:
            return gen_series.get(f.id, [0.0] * nb)

        def cust_arr(c: Customer) -> list[float]:
            return con_series.get(c.id, [0.0] * nb)

        def cap_arr(farm_id: int, cap: float) -> list[float]:
            # spread the monthly cap across buckets by the farm's actual profile
            prof = gen_series.get(farm_id) or [0.0] * nb
            s = sum(prof)
            return [cap / nb] * nb if s <= 0 else [cap * p / s for p in prof]

        def reduce24(series: list[float]) -> list[float]:
            return hour_of_day_sums(series, ndays)

        source, modeled, note = "interval", False, _INTERVAL_NOTE
    else:
        ndays, nb = 1, 24
        # each site is shaped by its own technology: wind night-strong, solar a
        # midday bell — the two fill each other's gaps (風光互補).
        shapes = {f.id: generation_shape(technology(f.farm_type)) for f in farm_rows}
        default_shape = generation_shape("wind")

        def farm_arr(f: WindFarm) -> list[float]:
            return to_hourly(gen_totals.get(f.id, 0.0), shapes[f.id])

        def cust_arr(c: Customer) -> list[float]:
            return to_hourly(con_totals.get(c.id, 0.0), load_shape(c.industry))

        def cap_arr(farm_id: int, cap: float) -> list[float]:
            return to_hourly(cap, shapes.get(farm_id, default_shape))

        def reduce24(series: list[float]) -> list[float]:
            return series

        source, modeled, note = "modeled", True, _MODELED_NOTE

    farms = [HourlyFarm(f.id, tuple(farm_arr(f))) for f in farm_rows]
    customers = [HourlyCustomer(c.id, tuple(cust_arr(c))) for c in cust_rows]

    eligible = [
        c
        for c in db.execute(select(Contract).order_by(Contract.id)).scalars()
        if c.status.value == "active" and c.start_date <= end and c.end_date >= start
    ]
    order_rank = {
        c.id: i
        for i, c in enumerate(
            sorted(eligible, key=lambda k: (k.start_date, k.contract_number))
        )
    }

    def build_contracts(
        cap_fn: Callable[[int, float], list[float]],
        skip_farms: frozenset[int] = frozenset(),
    ) -> list[HourlyContract]:
        out: list[HourlyContract] = []
        for c in eligible:
            if c.wind_farm_id in skip_farms:
                continue
            cap = contract_terms.monthly_volume_cap(
                c.contracted_energy_mwh, c.monthly_shares, month
            )
            out.append(
                HourlyContract(
                    contract_id=c.id,
                    contract_number=c.contract_number,
                    wind_farm_id=c.wind_farm_id,
                    customer_id=c.customer_id,
                    priority=c.priority,
                    percentage=c.contracted_percentage,
                    hourly_cap=(
                        tuple(cap_fn(c.wind_farm_id, cap)) if cap is not None else None
                    ),
                    order=order_rank[c.id],
                )
            )
        return out

    outcome = match_hourly(farms, customers, build_contracts(cap_arr))

    # 風光互補 (B4): same load, wind assets only — the baseline the solar bell is
    # measured against. Nothing to compare when the portfolio has no solar.
    solar_ids = frozenset(f.id for f in farm_rows if technology(f.farm_type) == "solar")
    wind_only_cfe: float | None = None
    uplift: float | None = None
    solar_by_hour: list[float] | None = None
    wind_only_by_customer: dict[int, float] = {}
    if solar_ids:
        solar_series = [0.0] * nb
        for f in farms:
            if f.farm_id in solar_ids:
                for i, v in enumerate(f.gen):
                    solar_series[i] += v
        solar_by_hour = reduce24(solar_series)
        wind_only = match_hourly(
            [f for f in farms if f.farm_id not in solar_ids],
            customers,
            build_contracts(cap_arr, skip_farms=solar_ids),
        )
        wind_only_cfe = wind_only.cfe_percent
        uplift = round(outcome.cfe_percent - wind_only_cfe, 2)
        wind_only_by_customer = {
            c.customer_id: c.cfe_percent for c in wind_only.customers
        }

    # 儲能 (B5): 把外溢挪到缺口時段。跑在風光對照之後,三段式讀數才不重疊——
    # uplift_pt 是太陽能的貢獻、storage_uplift_pt 是電池的貢獻。
    battery_rows = list(db.execute(select(Battery).order_by(Battery.id)).scalars())
    no_storage_cfe: float | None = None
    storage_uplift: float | None = None
    soc_series: list[float] | None = None
    discharged_series: list[float] | None = None
    charged_series: list[float] | None = None
    no_storage_by_customer: dict[int, float] = {}
    if battery_rows:
        specs = [
            BatterySpec(
                battery_id=b.id,
                customer_id=b.customer_id,
                capacity_mwh=b.energy_capacity_mwh,
                power_mw=b.power_mw,
                efficiency=b.round_trip_efficiency_percent / 100.0,
                initial_soc_mwh=b.energy_capacity_mwh * b.initial_soc_percent / 100.0,
            )
            for b in battery_rows
        ]
        # 每座案場的簽約客戶,依引擎排合約的同一把尺 → 決定充電輪 1 的先後。
        farm_customer_order: dict[int, list[int]] = {}
        for c in sorted(eligible, key=lambda k: (k.priority, order_rank[k.id], k.id)):
            seen = farm_customer_order.setdefault(c.wind_farm_id, [])
            if c.customer_id not in seen:
                seen.append(c.customer_id)

        storage = apply_storage(outcome, specs, farm_customer_order)
        no_storage_cfe = outcome.cfe_percent
        no_storage_by_customer = {
            c.customer_id: c.cfe_percent for c in outcome.customers
        }
        outcome = with_storage(outcome, storage, specs)
        storage_uplift = round(outcome.cfe_percent - no_storage_cfe, 2)

        def _sum_batteries(series: dict[int, list[float]]) -> list[float]:
            total = [0.0] * nb
            for arr in series.values():
                for i, v in enumerate(arr):
                    total[i] += v
            return total

        # 充放是流量 → 跟其他曲線一樣照 reduce24 加總。
        discharged_series = reduce24(_sum_batteries(storage.discharged_by_hour))
        charged_series = reduce24(_sum_batteries(storage.charged_by_hour))
        # SOC 是存量,不能加總——interval 模式下 31 天相加會變成 31 倍容量,
        # 標成 MWh 就是錯的。取同一小時的日均，畫出來才是一顆真實電池的容量尺度。
        soc_series = [v / ndays for v in reduce24(_sum_batteries(storage.soc_by_hour))]

    # "帳面" upper bound: match period totals in a single bucket (no timing).
    paper_farms = [HourlyFarm(f.id, (gen_totals.get(f.id, 0.0),)) for f in farm_rows]
    paper_customers = [
        HourlyCustomer(c.id, (con_totals.get(c.id, 0.0),)) for c in cust_rows
    ]
    paper = match_hourly(
        paper_farms,
        paper_customers,
        build_contracts(lambda _fid, cap: [cap]),
    )
    paper_by_customer = {c.customer_id: c.cfe_percent for c in paper.customers}

    farm_name = {f.id: f.name for f in farm_rows}
    cust_name = {c.id: c.company_name for c in cust_rows}
    cust_industry = {c.id: c.industry for c in cust_rows}

    def cust_base(cid: int) -> float | None:
        """該客戶在「只風電」對照組的 CFE%（投組沒有光電就沒有對照組）。"""
        return wind_only_by_customer.get(cid, 0.0) if solar_ids else None

    def cust_uplift(cid: int, cfe: float) -> float | None:
        base = cust_base(cid)
        return None if base is None else round(cfe - base, 2)

    customers_out = [
        HourlyCustomerOut(
            customer_id=c.customer_id,
            name=cust_name.get(c.customer_id, str(c.customer_id)),
            industry=cust_industry.get(c.customer_id),
            consumption_mwh=c.consumption_mwh,
            matched_mwh=c.matched_mwh,
            cfe_percent=c.cfe_percent,
            paper_re_percent=paper_by_customer.get(c.customer_id, 0.0),
            matched_by_hour=reduce24(c.matched_by_hour),
            shortfall_by_hour=reduce24(c.shortfall_by_hour),
            wind_only_cfe_percent=cust_base(c.customer_id),
            uplift_pt=cust_uplift(c.customer_id, c.cfe_percent),
            no_storage_cfe_percent=(
                no_storage_by_customer.get(c.customer_id) if battery_rows else None
            ),
            storage_uplift_pt=(
                round(c.cfe_percent - no_storage_by_customer.get(c.customer_id, 0.0), 2)
                if battery_rows
                else None
            ),
        )
        for c in outcome.customers
    ]
    if customer_id is not None:
        customers_out = [c for c in customers_out if c.customer_id == customer_id]

    farms_out = [
        HourlyFarmOut(
            wind_farm_id=f.farm_id,
            name=farm_name.get(f.farm_id, str(f.farm_id)),
            generated_mwh=f.generated_mwh,
            matched_mwh=f.matched_mwh,
            surplus_mwh=f.surplus_mwh,
        )
        for f in outcome.farms
    ]

    heatmap = None
    if source == "interval":
        heatmap = HeatmapOut(
            days=day_labels(start, ndays),
            values=heatmap_cfe(
                outcome.matched_by_hour, outcome.consumption_by_hour, ndays
            ),
        )

    return HourlyMatchingResult(
        period=period,
        source=source,
        modeled=modeled,
        note=note,
        hours=24,
        days=ndays,
        heatmap=heatmap,
        cfe_percent=outcome.cfe_percent,
        paper_re_percent=paper.cfe_percent,
        wind_only_cfe_percent=wind_only_cfe,
        uplift_pt=uplift,
        solar_generation_by_hour=solar_by_hour,
        no_storage_cfe_percent=no_storage_cfe,
        storage_uplift_pt=storage_uplift,
        soc_by_hour=soc_series,
        discharged_by_hour=discharged_series,
        charged_by_hour=charged_series,
        total_consumption_mwh=outcome.total_consumption_mwh,
        total_matched_mwh=outcome.total_matched_mwh,
        total_surplus_mwh=sum(outcome.surplus_by_hour),
        total_shortfall_mwh=sum(outcome.shortfall_by_hour),
        generation_by_hour=reduce24(outcome.generation_by_hour),
        consumption_by_hour=reduce24(outcome.consumption_by_hour),
        matched_by_hour=reduce24(outcome.matched_by_hour),
        surplus_by_hour=reduce24(outcome.surplus_by_hour),
        shortfall_by_hour=reduce24(outcome.shortfall_by_hour),
        customers=customers_out,
        farms=farms_out,
    )
