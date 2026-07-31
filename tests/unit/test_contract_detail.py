"""合約詳情：綁定約束分類與加購空間判定。

引擎的 reason 是給人讀的字串,這裡把它變成可上色、可統計的代碼。
「有沒有加購空間」則是三個條件的合取——少一個,那句話就是假的。
"""

from __future__ import annotations

import pytest

from app.services.contract_detail_service import classify_binding, has_headroom


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
