"""合約詳情：綁定約束分類與加購空間判定。

引擎的 reason 是給人讀的字串,這裡把它變成可上色、可統計的代碼。
「有沒有加購空間」則是三個條件的合取——少一個,那句話就是假的。
"""

from __future__ import annotations

import calendar
from datetime import date

import pytest

from app.models import ConsumptionData, Contract, Customer, GenerationData, WindFarm
from app.models.enums import ContractStatus
from app.services.contract_detail_service import (
    classify_binding,
    compute_contract_detail,
    has_headroom,
)


@pytest.mark.parametrize(
    ("reason", "expected"),
    [
        (
            "allocated 1250.0 MWh (limited by contract cap)",
            (["contract_cap"], "contract_cap"),
        ),
        (
            "allocated 900.0 MWh (limited by wind farm supply)",
            (["farm_supply"], "farm_supply"),
        ),
        (
            "allocated 800.0 MWh (limited by customer demand)",
            (["customer_demand"], "customer_demand"),
        ),
        ("allocated 5.0 MWh (limited by available supply)", ([], "none")),
        ("no allocation", ([], "none")),
    ],
)
def test_single_constraint_is_classified(reason, expected):
    assert classify_binding(reason) == expected


def test_multiple_constraints_keep_a_fixed_precedence():
    """同時綁定時只挑一個上色。案場供給用盡最硬——調高上限也拿不到更多電。"""
    binding, primary = classify_binding(
        "allocated 300.0 MWh (limited by wind farm supply, contract cap)"
    )
    assert binding == ["farm_supply", "contract_cap"]
    assert primary == "farm_supply"


def test_precedence_is_supply_then_demand_then_cap():
    _, primary = classify_binding(
        "allocated 0.0 MWh (limited by customer demand, contract cap)"
    )
    assert primary == "customer_demand"


@pytest.mark.parametrize(
    ("reason", "primary"),
    [
        ("no allocation: wind farm has no remaining generation", "farm_supply"),
        (
            "no allocation: customer consumption already fully covered",
            "customer_demand",
        ),
        ("no allocation: contract cap is zero", "contract_cap"),
    ],
)
def test_zero_allocation_still_names_its_constraint(reason, primary):
    """零分配時引擎有講原因,退回 none 等於丟掉已知資訊。"""
    assert classify_binding(reason)[1] == primary


def test_headroom_needs_all_three_conditions():
    assert has_headroom("contract_cap", 500.0, 300.0) is True


@pytest.mark.parametrize(
    ("primary", "farm_left", "cust_unmet"),
    [
        ("farm_supply", 500.0, 300.0),  # 不是被上限卡住 → 調高上限無用
        ("contract_cap", 0.0, 300.0),  # 案場沒餘電 → 調高上限也拿不到
        ("contract_cap", 500.0, 0.0),  # 客戶已吃飽 → 多給也用不掉
    ],
)
def test_headroom_is_false_when_any_condition_fails(primary, farm_left, cust_unmet):
    assert has_headroom(primary, farm_left, cust_unmet) is False


WIND_SHAPE = [1.35, 1.25, 1.05, 0.85, 0.70, 0.55, 0.55, 0.60, 0.85, 1.15, 1.30, 1.40]


def _month_bounds(year: int, month: int) -> tuple[date, date]:
    last = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last)


def _build(db, **contract_kw):
    """一場一戶一約,整年每月發電 3000 MWh、用電 5000 MWh。"""
    farm = WindFarm(
        code="WF-T",
        name="測試風場",
        installed_capacity_mw=100,
        feed_in_price_per_kwh=4.0,
    )
    cust = Customer(code="CU-T", company_name="測試用電廠", re_target_percent=50.0)
    db.add_all([farm, cust])
    db.flush()
    for m in range(1, 13):
        start, end = _month_bounds(2024, m)
        db.add(
            GenerationData(
                wind_farm_id=farm.id,
                period_start=start,
                period_end=end,
                generated_energy_mwh=3000.0,
                data_source="test",
            )
        )
        db.add(
            ConsumptionData(
                customer_id=cust.id,
                period_start=start,
                period_end=end,
                consumed_energy_mwh=5000.0,
                data_source="test",
            )
        )
    kw = {
        "contract_number": "PPA-T-1",
        "wind_farm_id": farm.id,
        "customer_id": cust.id,
        "start_date": date(2024, 1, 1),
        "end_date": date(2030, 12, 31),
        "contracted_energy_mwh": 12000.0,
        "price_per_kwh": 5.0,
        "priority": 1,
        "status": ContractStatus.ACTIVE,
    }
    kw.update(contract_kw)
    contract = Contract(**kw)
    db.add(contract)
    db.commit()
    return contract, farm, cust


def test_returns_twelve_months(db):
    contract, _, _ = _build(db)
    d = compute_contract_detail(db, contract.id, 2024)
    assert len(d.months) == 12
    assert [m.month for m in d.months] == list(range(1, 13))
    assert d.months[2].period == "2024-03"
    assert d.has_period_data is True


def test_flat_annual_volume_spreads_evenly(db):
    contract, _, _ = _build(db)
    d = compute_contract_detail(db, contract.id, 2024)
    assert all(m.cap_mwh == pytest.approx(1000.0) for m in d.months)
    assert d.months[0].cap_source == "volume"


def test_monthly_shares_shape_the_cap(db):
    contract, _, _ = _build(db, monthly_shares=WIND_SHAPE)
    d = compute_contract_detail(db, contract.id, 2024)
    total = sum(WIND_SHAPE)
    assert d.months[0].cap_mwh == pytest.approx(12000.0 * WIND_SHAPE[0] / total)
    assert d.months[5].cap_mwh == pytest.approx(12000.0 * WIND_SHAPE[5] / total)
    assert d.months[0].cap_mwh > d.months[5].cap_mwh  # 冬高夏低
    assert d.monthly_share_fractions is not None
    assert sum(d.monthly_share_fractions) == pytest.approx(1.0)


def test_no_monthly_shares_means_no_fractions(db):
    contract, _, _ = _build(db)
    assert (
        compute_contract_detail(db, contract.id, 2024).monthly_share_fractions is None
    )


def test_uncapped_contract_keeps_utilization_null(db):
    """未設上限 ≠ 使用率 0%。null 不能變成數字。"""
    contract, _, _ = _build(db, contracted_energy_mwh=None, contracted_percentage=None)
    d = compute_contract_detail(db, contract.id, 2024)
    assert all(m.cap_mwh is None for m in d.months)
    assert all(m.utilization_percent is None for m in d.months)
    assert d.months[0].cap_source == "none"
    assert d.totals.cap_mwh is None
    assert d.totals.utilization_percent is None


def test_percentage_cap_tracks_generation(db):
    contract, _, _ = _build(db, contracted_energy_mwh=None, contracted_percentage=50.0)
    d = compute_contract_detail(db, contract.id, 2024)
    assert all(m.cap_mwh == pytest.approx(1500.0) for m in d.months)
    assert d.months[0].cap_source == "percentage"


def test_take_or_pay_floor_and_shortfall(db):
    """年電量 36000（月 3000）> 案場月發電 3000 → 拿滿 3000,門檻 90% = 2700,不差額。"""
    contract, _, _ = _build(db, contracted_energy_mwh=36000.0, min_offtake_percent=90.0)
    d = compute_contract_detail(db, contract.id, 2024)
    assert d.months[0].min_offtake_mwh == pytest.approx(2700.0)
    assert d.months[0].shortfall_mwh == pytest.approx(0.0)
    assert d.totals.shortfall_months == 0


def test_shortfall_is_reported_when_supply_falls_short(db):
    """年電量 60000（月 5000）,案場只發 3000 → 門檻 4500,每月差額 1500。"""
    contract, _, _ = _build(db, contracted_energy_mwh=60000.0, min_offtake_percent=90.0)
    d = compute_contract_detail(db, contract.id, 2024)
    assert d.months[0].allocated_mwh == pytest.approx(3000.0)
    assert d.months[0].shortfall_mwh == pytest.approx(1500.0)
    assert d.totals.shortfall_months == 12
    assert d.totals.shortfall_mwh == pytest.approx(18000.0)


def test_out_of_force_months_are_not_zero_allocations(db):
    """2025 才生效的合約,2024 的每個月是「未生效」而不是「拿了 0」。"""
    contract, _, _ = _build(db, start_date=date(2025, 1, 1))
    d = compute_contract_detail(db, contract.id, 2024)
    assert all(m.in_force is False for m in d.months)
    assert all(m.binding_primary == "not_in_force" for m in d.months)
    assert all(m.binding == [] for m in d.months)
    assert all(m.cap_mwh is None for m in d.months)
    assert all(m.skip_reason for m in d.months)
    assert d.totals.months_in_force == 0
    assert d.totals.allocated_mwh == pytest.approx(0.0)


def test_binding_counts_pin_the_actual_distribution(db):
    """釘分佈,不是釘總和。「加起來有 12」跟 len(months) == 12 是同一句話,不會紅。"""
    contract, _, _ = _build(db)
    d = compute_contract_detail(db, contract.id, 2024)
    assert d.totals.binding_counts == {"contract_cap": 12}


def test_headroom_is_wired_through_with_its_two_inputs(db):
    """cap-bound 且案場有餘電、客戶有未滿足用電 → 有加購空間,且兩個依據都回報得出來。

    在這之前沒有任何測試釘過 headroom 為 True、也沒有釘過 totals.headroom_months,
    純函數測得再好,接線斷了照樣不會紅。

    兩個依據刻意取不同的數字(2000 / 4000):_month_context() 回傳的是一個
    (farm_left, cust_unmet) 的位置元組,對調就會被這兩行抓到。
    （has_headroom 後兩個引數本身是對稱的——兩者都只判 > EPS——所以「對調
    has_headroom 的引數」這種變異在任何 fixture 下都觀察不到,不是這裡的目標。）
    """
    contract, _, _ = _build(db)
    d = compute_contract_detail(db, contract.id, 2024)
    jan = d.months[0]
    assert jan.binding_primary == "contract_cap"
    assert jan.headroom is True
    assert jan.farm_unallocated_mwh == pytest.approx(2000.0)
    assert jan.customer_unmet_mwh == pytest.approx(4000.0)
    assert d.totals.headroom_months == 12


def test_annual_totals_equal_the_sum_of_months(db):
    """年度合計必須就是 12 個月加總——這個專案栽過加總錯誤的跟頭。"""
    contract, _, _ = _build(db, contracted_energy_mwh=60000.0, min_offtake_percent=90.0)
    d = compute_contract_detail(db, contract.id, 2024)
    assert d.totals.allocated_mwh == pytest.approx(
        sum(m.allocated_mwh for m in d.months)
    )
    assert d.totals.shortfall_mwh == pytest.approx(
        sum(m.shortfall_mwh for m in d.months)
    )
    assert d.totals.min_offtake_mwh == pytest.approx(
        sum(m.min_offtake_mwh for m in d.months)
    )


def test_higher_priority_siblings_are_counted(db):
    contract, farm, cust = _build(db, priority=3)
    db.add(
        Contract(
            contract_number="PPA-T-2",
            wind_farm_id=farm.id,
            customer_id=cust.id,
            start_date=date(2024, 1, 1),
            end_date=date(2030, 12, 31),
            contracted_percentage=50.0,
            price_per_kwh=5.0,
            priority=1,
            status=ContractStatus.ACTIVE,
        )
    )
    db.commit()
    d = compute_contract_detail(db, contract.id, 2024)
    assert d.higher_priority_sibling_count == 1


def test_top_priority_contract_has_no_higher_siblings(db):
    """本合約已是該案場最高優先序時必須是 0——否則畫面會憑空指控它被插隊。"""
    contract, _, _ = _build(db, priority=1)
    assert (
        compute_contract_detail(db, contract.id, 2024).higher_priority_sibling_count
        == 0
    )


def test_year_without_measurements_is_flagged(db):
    contract, _, _ = _build(db)
    d = compute_contract_detail(db, contract.id, 2023)
    assert d.has_period_data is False
    assert len(d.months) == 12


def test_unknown_contract_raises_not_found(db):
    from app.core.exceptions import NotFoundError

    with pytest.raises(NotFoundError):
        compute_contract_detail(db, 9999, 2024)


def test_money_identities_hold_every_month(db):
    """兩條恆等式。公式跟結算單同一套,差異只該來自引擎不同。"""
    contract, _, _ = _build(db, contracted_energy_mwh=60000.0, min_offtake_percent=90.0)
    d = compute_contract_detail(db, contract.id, 2024)
    for m in d.months:
        assert m.buyer_payable == pytest.approx(
            m.energy_cost + m.wheeling_fee + m.take_or_pay_charge
        )
        assert m.retailer_margin == pytest.approx(
            m.energy_cost - m.seller_receivable - m.wheeling_fee + m.take_or_pay_charge
        )


def test_money_uses_contract_price_and_farm_feed_in(db):
    """月 3000 MWh × 5.0 元 = 1500 萬綠電費；應收 3000 MWh × 4.0 元 = 1200 萬。"""
    contract, _, _ = _build(db, contracted_energy_mwh=36000.0)
    d = compute_contract_detail(db, contract.id, 2024)
    jan = d.months[0]
    assert jan.allocated_mwh == pytest.approx(3000.0)
    assert jan.price_per_kwh == pytest.approx(5.0)
    assert jan.energy_cost == pytest.approx(3000.0 * 1000 * 5.0)
    assert jan.seller_receivable == pytest.approx(3000.0 * 1000 * 4.0)
    assert jan.wheeling_fee == pytest.approx(3000.0 * 1000 * d.wheeling_fee_per_kwh)


def test_cpi_escalates_the_price_by_year(db):
    contract, _, _ = _build(
        db,
        price_escalation_percent=2.5,
        price_base_year=2022,
    )
    d = compute_contract_detail(db, contract.id, 2024)
    assert d.months[0].price_per_kwh == pytest.approx(5.0 * 1.025**2)


def test_price_before_the_base_year_is_not_discounted(db):
    contract, _, _ = _build(db, price_escalation_percent=2.5, price_base_year=2030)
    d = compute_contract_detail(db, contract.id, 2024)
    assert d.months[0].price_per_kwh == pytest.approx(5.0)


def test_contract_without_a_price_reports_no_money_at_all(db):
    """不拿躉售價代入讓毛利變成 0——那是個看起來合理但不真實的數字。"""
    contract, _, _ = _build(db, price_per_kwh=None)
    d = compute_contract_detail(db, contract.id, 2024)
    assert d.has_price is False
    for m in d.months:
        assert m.price_per_kwh is None
        assert m.energy_cost is None
        assert m.buyer_payable is None
        assert m.retailer_margin is None
    assert d.totals.buyer_payable is None
    assert d.totals.margin_percent is None


def test_farm_without_a_feed_in_price_is_flagged(db):
    contract, farm, _ = _build(db)
    farm.feed_in_price_per_kwh = None
    db.commit()
    d = compute_contract_detail(db, contract.id, 2024)
    assert d.used_default_feed_in is True
    assert d.feed_in_price_per_kwh > 0


def test_annual_money_equals_the_sum_of_months(db):
    contract, _, _ = _build(db, contracted_energy_mwh=60000.0, min_offtake_percent=90.0)
    d = compute_contract_detail(db, contract.id, 2024)
    t = d.totals
    assert t.buyer_payable == pytest.approx(sum(m.buyer_payable for m in d.months))
    assert t.seller_receivable == pytest.approx(
        sum(m.seller_receivable for m in d.months)
    )
    assert t.retailer_margin == pytest.approx(sum(m.retailer_margin for m in d.months))
    assert t.margin_percent == pytest.approx(t.retailer_margin / t.buyer_payable * 100)


def test_out_of_force_months_cost_nothing_but_are_not_null(db):
    """有售電價的合約,未生效月份金額是 0（可加總）,不是 None。"""
    contract, _, _ = _build(db, start_date=date(2025, 1, 1))
    d = compute_contract_detail(db, contract.id, 2024)
    assert all(m.buyer_payable == 0.0 for m in d.months)
    assert d.totals.margin_percent is None  # 應付為 0 → 毛利率無意義
