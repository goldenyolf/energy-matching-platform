"""B5 的兩輪充電優先序,以及把充放結果併回 outcome。"""

from __future__ import annotations

import pytest

from app.matching.hourly_matching import (
    HourlyCustomerResult,
    HourlyFarmResult,
    HourlyOutcome,
)
from app.matching.storage import BatterySpec, apply_storage, with_storage


def _outcome(
    farm_surplus: dict[int, list[float]],
    cust_shortfall: dict[int, list[float]],
    cust_matched: dict[int, list[float]] | None = None,
) -> HourlyOutcome:
    hours = len(next(iter(farm_surplus.values())))
    out = HourlyOutcome(hours=hours)
    for fid, sur in farm_surplus.items():
        out.farms.append(
            HourlyFarmResult(
                farm_id=fid,
                generated_mwh=sum(sur),
                matched_mwh=0.0,
                surplus_mwh=sum(sur),
                surplus_by_hour=list(sur),
            )
        )
    for cid, short in cust_shortfall.items():
        matched = list((cust_matched or {}).get(cid, [0.0] * hours))
        out.customers.append(
            HourlyCustomerResult(
                customer_id=cid,
                consumption_mwh=sum(short) + sum(matched),
                matched_mwh=sum(matched),
                cfe_percent=0.0,
                matched_by_hour=matched,
                shortfall_by_hour=list(short),
            )
        )
    out.consumption_by_hour = [
        sum(c.matched_by_hour[h] + c.shortfall_by_hour[h] for c in out.customers)
        for h in range(hours)
    ]
    out.generation_by_hour = [
        sum(f.surplus_by_hour[h] for f in out.farms) for h in range(hours)
    ]
    out.matched_by_hour = [
        sum(c.matched_by_hour[h] for c in out.customers) for h in range(hours)
    ]
    out.surplus_by_hour = list(out.generation_by_hour)
    out.shortfall_by_hour = [
        sum(c.shortfall_by_hour[h] for c in out.customers) for h in range(hours)
    ]
    out.total_consumption_mwh = sum(out.consumption_by_hour)
    out.total_matched_mwh = sum(out.matched_by_hour)
    return out


def _bat(bid: int, cid: int, **kw) -> BatterySpec:
    base = {
        "battery_id": bid,
        "customer_id": cid,
        "capacity_mwh": 100.0,
        "power_mw": 100.0,
        "efficiency": 1.0,
        "initial_soc_mwh": 0.0,
    }
    base.update(kw)
    return BatterySpec(**base)


# 這些優先序測試都在 h0 充電。每位客戶在 h1 留一點缺口,電池才「放得出來」——
# 主人整段期間都沒缺口的電池不准充電（否則外溢會被它憑空吃掉,見 storage.py）。
_LATER_GAP = 5.0


def test_own_contract_battery_gets_the_surplus_first():
    # 案場 1 只外溢 30；客戶 10 有簽約、客戶 20 沒有 → 10 先吃滿。
    out = _outcome({1: [30.0, 0.0]}, {10: [0.0, _LATER_GAP], 20: [0.0, _LATER_GAP]})
    st = apply_storage(out, [_bat(1, 10), _bat(2, 20)], {1: [10]})
    assert st.charged_by_hour[1] == pytest.approx([30.0, 0.0])
    assert st.charged_by_hour[2] == pytest.approx([0.0, 0.0])


def test_leftover_surplus_opens_up_to_other_batteries():
    # 案場 1 外溢 130；簽約客戶的電池只吃得下 100 → 剩 30 給沒簽約的。
    out = _outcome({1: [130.0, 0.0]}, {10: [0.0, _LATER_GAP], 20: [0.0, _LATER_GAP]})
    st = apply_storage(out, [_bat(1, 10, capacity_mwh=100.0), _bat(2, 20)], {1: [10]})
    assert st.charged_by_hour[1] == pytest.approx([100.0, 0.0])
    assert st.charged_by_hour[2] == pytest.approx([30.0, 0.0])


def test_contract_order_decides_who_charges_first_on_the_same_farm():
    # 兩位客戶都簽了案場 1,合約優先序是 [20, 10] → 20 先吃。
    out = _outcome({1: [40.0, 0.0]}, {10: [0.0, _LATER_GAP], 20: [0.0, _LATER_GAP]})
    st = apply_storage(
        out, [_bat(1, 10), _bat(2, 20, capacity_mwh=40.0)], {1: [20, 10]}
    )
    assert st.charged_by_hour[2] == pytest.approx([40.0, 0.0])
    assert st.charged_by_hour[1] == pytest.approx([0.0, 0.0])


def test_charge_sources_are_recorded_per_farm():
    out = _outcome({1: [20.0, 0.0], 2: [50.0, 0.0]}, {10: [0.0, _LATER_GAP]})
    st = apply_storage(out, [_bat(1, 10)], {1: [10]})
    assert st.charged_from_farm[1] == pytest.approx({1: 20.0, 2: 50.0})


def test_with_storage_moves_discharge_into_matched():
    out = _outcome({1: [40.0, 0.0]}, {10: [0.0, 40.0]}, {10: [60.0, 0.0]})
    bats = [_bat(1, 10)]
    st = apply_storage(out, bats, {1: [10]})

    merged = with_storage(out, st, bats)
    c = merged.customers[0]
    assert c.matched_by_hour == pytest.approx([60.0, 40.0])
    assert c.shortfall_by_hour == pytest.approx([0.0, 0.0])
    assert c.matched_mwh == pytest.approx(100.0)
    assert c.cfe_percent == pytest.approx(100.0)
    assert merged.farms[0].surplus_by_hour == pytest.approx([0.0, 0.0])
    assert merged.cfe_percent == pytest.approx(100.0)


def test_with_storage_leaves_the_original_outcome_alone():
    out = _outcome({1: [40.0, 0.0]}, {10: [0.0, 40.0]}, {10: [60.0, 0.0]})
    bats = [_bat(1, 10)]
    merged = with_storage(out, apply_storage(out, bats, {1: [10]}), bats)

    assert merged is not out
    assert out.customers[0].matched_by_hour == pytest.approx([60.0, 0.0])  # 原件未動
    assert out.customers[0].shortfall_by_hour == pytest.approx([0.0, 40.0])
