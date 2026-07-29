"""B5 儲能充放層：純函式、確定性、逐步可稽核。"""

from __future__ import annotations

import pytest

from app.matching.hourly_matching import (
    HourlyCustomerResult,
    HourlyFarmResult,
    HourlyOutcome,
)
from app.matching.storage import BatterySpec, apply_storage


def _outcome(surplus: list[float], shortfall: list[float]) -> HourlyOutcome:
    """一座案場、一位客戶的最小 outcome（只有 storage 會讀的那幾個欄位）。"""
    hours = len(surplus)
    out = HourlyOutcome(hours=hours)
    out.farms.append(
        HourlyFarmResult(
            farm_id=1,
            generated_mwh=sum(surplus),
            matched_mwh=0.0,
            surplus_mwh=sum(surplus),
            surplus_by_hour=list(surplus),
        )
    )
    out.customers.append(
        HourlyCustomerResult(
            customer_id=10,
            consumption_mwh=sum(shortfall),
            matched_mwh=0.0,
            cfe_percent=0.0,
            matched_by_hour=[0.0] * hours,
            shortfall_by_hour=list(shortfall),
        )
    )
    return out


def _battery(**kw) -> BatterySpec:
    base = {
        "battery_id": 1,
        "customer_id": 10,
        "capacity_mwh": 100.0,
        "power_mw": 50.0,
        "efficiency": 1.0,
        "initial_soc_mwh": 0.0,
    }
    base.update(kw)
    return BatterySpec(**base)


def test_charges_from_surplus_then_discharges_into_shortfall():
    # h0 外溢 40、無缺口 → 充；h1 缺口 40、無外溢 → 放。
    st = apply_storage(_outcome([40.0, 0.0], [0.0, 40.0]), [_battery()], {1: [10]})
    assert st.charged_by_hour[1] == pytest.approx([40.0, 0.0])
    assert st.discharged_by_hour[1] == pytest.approx([0.0, 40.0])
    assert st.soc_by_hour[1] == pytest.approx([40.0, 0.0])
    assert st.shortfall_left_by_hour[10] == pytest.approx([0.0, 0.0])
    assert st.surplus_left_by_hour[1] == pytest.approx([0.0, 0.0])


def test_power_limits_both_charge_and_discharge():
    st = apply_storage(
        _outcome([90.0, 0.0], [0.0, 90.0]), [_battery(power_mw=50.0)], {1: [10]}
    )
    assert st.charged_by_hour[1][0] == pytest.approx(50.0)  # 充電受功率上限
    assert st.discharged_by_hour[1][1] == pytest.approx(50.0)  # 放電同一上限
    assert st.surplus_left_by_hour[1][0] == pytest.approx(40.0)  # 吃不下的仍外溢


def test_capacity_caps_the_stored_energy():
    st = apply_storage(
        _outcome([80.0, 80.0, 0.0], [0.0, 0.0, 500.0]),
        [_battery(capacity_mwh=100.0, power_mw=80.0)],
        {1: [10]},
    )
    assert max(st.soc_by_hour[1]) <= 100.0 + 1e-9
    assert st.charged_by_hour[1] == pytest.approx([80.0, 20.0, 0.0])


def test_a_battery_never_charges_and_discharges_in_the_same_hour():
    # 同一小時既有外溢也有缺口 → 缺口優先,放電,不充電。
    st = apply_storage(
        _outcome([30.0], [30.0]), [_battery(initial_soc_mwh=30.0)], {1: [10]}
    )
    assert st.discharged_by_hour[1][0] == pytest.approx(30.0)
    assert st.charged_by_hour[1][0] == pytest.approx(0.0)
    assert st.surplus_left_by_hour[1][0] == pytest.approx(30.0)  # 外溢原封不動


def test_round_trip_efficiency_is_taken_off_the_discharge():
    st = apply_storage(
        _outcome([100.0, 0.0], [0.0, 100.0]),
        [_battery(efficiency=0.5, power_mw=100.0)],
        {1: [10]},
    )
    assert st.charged_by_hour[1][0] == pytest.approx(100.0)  # 充電 1:1 進 SOC
    assert st.discharged_by_hour[1][1] == pytest.approx(50.0)  # 送出 SOC × η
    assert st.soc_by_hour[1][1] == pytest.approx(0.0)  # SOC 扣 送出/η


def test_energy_conservation_identity_holds():
    b = _battery(efficiency=0.8, initial_soc_mwh=10.0, power_mw=25.0)
    st = apply_storage(
        _outcome([30.0, 0.0, 20.0, 0.0], [0.0, 15.0, 0.0, 40.0]), [b], {1: [10]}
    )
    delivered = sum(st.discharged_by_hour[1])
    charged = sum(st.charged_by_hour[1])
    soc_end = st.soc_by_hour[1][-1]
    # Σ送出 = (期初SOC + Σ充入 − 期末SOC) × η
    assert delivered == pytest.approx(
        (b.initial_soc_mwh + charged - soc_end) * b.efficiency
    )


def test_soc_carries_across_days():
    # 48 小時：第 1 天充、第 2 天放 → SOC 必須跨日帶過去。
    surplus = [50.0] + [0.0] * 47
    shortfall = [0.0] * 30 + [50.0] + [0.0] * 17
    st = apply_storage(_outcome(surplus, shortfall), [_battery()], {1: [10]})
    assert st.discharged_by_hour[1][30] == pytest.approx(50.0)


def test_is_deterministic():
    args = (_outcome([40.0, 0.0], [0.0, 40.0]), [_battery()], {1: [10]})
    first = apply_storage(*args)
    second = apply_storage(_outcome([40.0, 0.0], [0.0, 40.0]), [_battery()], {1: [10]})
    assert first.charged_by_hour == second.charged_by_hour
    assert first.discharged_by_hour == second.discharged_by_hour


def test_no_batteries_leaves_everything_untouched():
    st = apply_storage(_outcome([40.0, 0.0], [0.0, 40.0]), [], {1: [10]})
    assert st.surplus_left_by_hour[1] == pytest.approx([40.0, 0.0])
    assert st.shortfall_left_by_hour[10] == pytest.approx([0.0, 40.0])
    assert st.charged_by_hour == {}
