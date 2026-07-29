"""B5 — 客戶側儲能充放層（疊在逐時匹配引擎的輸出之上）。

``match_hourly`` 嚴格不跨小時：外溢就是外溢、缺口就是缺口。儲能是唯一能合法
打破這條規則的東西，所以它被做成**獨立的一層**而不是引擎裡的例外——引擎保持
純粹、可稽核、可回歸,這一層負責把外溢的電挪到缺口時段。

每小時的規則（可複述、可稽核）:

1. **放電優先**：客戶在該小時有缺口 → 送出 ``min(缺口, 功率, SOC × η)``，
   SOC 扣 ``送出 / η``。
2. **無缺口才充電**,且同一具電池同一小時不同時充放（物理真實）。充電分兩輪：
   輪 1 只吃「自家有簽約」的案場外溢（依合約優先序）,輪 2 才開放其他案場。
3. 每筆充電記錄來自哪座案場（``charged_from_farm``）,跨合約的度數流向留得住
   稽核軌跡。

能量守恆恆等式（測試會驗）::

    Σ送出 = (期初 SOC + Σ充入 − 期末 SOC) × η
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.matching.hourly_matching import (
    HourlyCustomerResult,
    HourlyFarmResult,
    HourlyOutcome,
)

_EPS = 1e-9


@dataclass(frozen=True)
class BatterySpec:
    """一具電池的物理規格（純資料，無 DB 相依）。"""

    battery_id: int
    customer_id: int
    capacity_mwh: float
    power_mw: float
    efficiency: float  # 往返效率 0–1
    initial_soc_mwh: float = 0.0


@dataclass
class StorageOutcome:
    hours: int
    charged_by_hour: dict[int, list[float]] = field(default_factory=dict)
    discharged_by_hour: dict[int, list[float]] = field(default_factory=dict)
    soc_by_hour: dict[int, list[float]] = field(default_factory=dict)
    # battery_id -> farm_id -> MWh（充電來源歸屬，未來做憑證溯源的地基）
    charged_from_farm: dict[int, dict[int, float]] = field(default_factory=dict)
    surplus_left_by_hour: dict[int, list[float]] = field(default_factory=dict)
    shortfall_left_by_hour: dict[int, list[float]] = field(default_factory=dict)


def apply_storage(
    outcome: HourlyOutcome,
    batteries: list[BatterySpec],
    farm_customer_order: dict[int, list[int]],
) -> StorageOutcome:
    """把外溢挪到缺口時段。``farm_customer_order`` 是每座案場的簽約客戶（依合約
    優先序），用來決定充電輪 1 的先後——沿用引擎排合約的同一把尺。"""
    hours = outcome.hours
    surplus = {f.farm_id: list(f.surplus_by_hour) for f in outcome.farms}
    shortfall = {c.customer_id: list(c.shortfall_by_hour) for c in outcome.customers}
    out = StorageOutcome(
        hours=hours,
        surplus_left_by_hour=surplus,
        shortfall_left_by_hour=shortfall,
    )
    if hours == 0 or not batteries:
        return out

    ordered = sorted(batteries, key=lambda b: b.battery_id)
    by_customer: dict[int, list[BatterySpec]] = {}
    for b in ordered:
        by_customer.setdefault(b.customer_id, []).append(b)
    soc = {
        b.battery_id: min(max(b.initial_soc_mwh, 0.0), b.capacity_mwh) for b in ordered
    }
    for b in ordered:
        out.charged_by_hour[b.battery_id] = [0.0] * hours
        out.discharged_by_hour[b.battery_id] = [0.0] * hours
        out.soc_by_hour[b.battery_id] = [0.0] * hours
        out.charged_from_farm[b.battery_id] = {}

    farm_ids = [f.farm_id for f in outcome.farms]

    def charge(b: BatterySpec, farm_id: int, h: int, busy: set[int]) -> None:
        if b.battery_id in busy or farm_id not in surplus:
            return
        take = min(
            surplus[farm_id][h],
            b.capacity_mwh - soc[b.battery_id],
            b.power_mw - out.charged_by_hour[b.battery_id][h],
        )
        if take <= _EPS:
            return
        surplus[farm_id][h] -= take
        soc[b.battery_id] += take
        out.charged_by_hour[b.battery_id][h] += take
        src = out.charged_from_farm[b.battery_id]
        src[farm_id] = src.get(farm_id, 0.0) + take

    for h in range(hours):
        busy: set[int] = set()  # 這小時已放電的電池,不再充電

        # 1) 放電優先
        for b in ordered:
            load_left = shortfall.get(b.customer_id)
            if load_left is None or load_left[h] <= _EPS:
                continue
            deliver = min(load_left[h], b.power_mw, soc[b.battery_id] * b.efficiency)
            if deliver <= _EPS:
                continue
            soc[b.battery_id] -= deliver / b.efficiency
            load_left[h] -= deliver
            out.discharged_by_hour[b.battery_id][h] += deliver
            busy.add(b.battery_id)

        # 2) 充電輪 1：自家合約的案場外溢（依該案場的合約優先序）
        for farm_id in farm_ids:
            for cid in farm_customer_order.get(farm_id, []):
                for b in by_customer.get(cid, []):
                    charge(b, farm_id, h, busy)

        # 3) 充電輪 2：剩下的外溢才開放給其他電池（依 battery_id）
        for farm_id in farm_ids:
            contracted = set(farm_customer_order.get(farm_id, []))
            for b in ordered:
                if b.customer_id in contracted:
                    continue
                charge(b, farm_id, h, busy)

        for b in ordered:
            out.soc_by_hour[b.battery_id][h] = soc[b.battery_id]

    return out


def with_storage(
    outcome: HourlyOutcome,
    storage: StorageOutcome,
    batteries: list[BatterySpec],
) -> HourlyOutcome:
    """把充放結果併回成一份**新的** outcome：放電計入 matched、缺口與外溢換成
    剩餘量、彙總欄位重算。原 outcome 不被修改,呼叫端才留得住「無儲」對照組。"""
    hours = outcome.hours
    delivered: dict[int, list[float]] = {}
    for b in batteries:
        arr = storage.discharged_by_hour.get(b.battery_id)
        if arr is None:
            continue
        tgt = delivered.setdefault(b.customer_id, [0.0] * hours)
        for h, v in enumerate(arr):
            tgt[h] += v

    out = HourlyOutcome(hours=hours)
    for c in outcome.customers:
        extra = delivered.get(c.customer_id, [0.0] * hours)
        matched = [m + x for m, x in zip(c.matched_by_hour, extra, strict=True)]
        matched_mwh = sum(matched)
        out.customers.append(
            HourlyCustomerResult(
                customer_id=c.customer_id,
                consumption_mwh=c.consumption_mwh,
                matched_mwh=matched_mwh,
                cfe_percent=(
                    matched_mwh / c.consumption_mwh * 100.0
                    if c.consumption_mwh > _EPS
                    else 0.0
                ),
                matched_by_hour=matched,
                shortfall_by_hour=list(
                    storage.shortfall_left_by_hour.get(
                        c.customer_id, c.shortfall_by_hour
                    )
                ),
            )
        )
    for f in outcome.farms:
        left = list(storage.surplus_left_by_hour.get(f.farm_id, f.surplus_by_hour))
        surplus_mwh = sum(left)
        out.farms.append(
            HourlyFarmResult(
                farm_id=f.farm_id,
                generated_mwh=f.generated_mwh,
                matched_mwh=f.generated_mwh - surplus_mwh,
                surplus_mwh=surplus_mwh,
                surplus_by_hour=left,
            )
        )

    out.consumption_by_hour = list(outcome.consumption_by_hour)
    out.generation_by_hour = list(outcome.generation_by_hour)
    out.matched_by_hour = [
        sum(c.matched_by_hour[h] for c in out.customers) for h in range(hours)
    ]
    out.surplus_by_hour = [
        sum(f.surplus_by_hour[h] for f in out.farms) for h in range(hours)
    ]
    out.shortfall_by_hour = [
        sum(c.shortfall_by_hour[h] for c in out.customers) for h in range(hours)
    ]
    out.total_consumption_mwh = sum(out.consumption_by_hour)
    out.total_matched_mwh = sum(out.matched_by_hour)
    out.cfe_percent = (
        out.total_matched_mwh / out.total_consumption_mwh * 100.0
        if out.total_consumption_mwh > _EPS
        else 0.0
    )
    return out
