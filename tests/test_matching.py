"""媒合引擎單元測試。"""

from __future__ import annotations

import pytest

from app.models import AllocationType, Dataset
from app.matching import match

from .conftest import make_company, make_contract, make_farm


def test_ratio_allocation(simple_dataset):
    """50% ratio 合約應分配案場一半的發電量。"""
    result = match(simple_dataset)
    assert len(result.allocations) == 1
    alloc = result.allocations[0]
    assert alloc.requested_mwh == pytest.approx(500.0)
    assert alloc.allocated_mwh == pytest.approx(500.0)
    assert alloc.curtailed is False


def test_volume_allocation():
    """volume 合約應直接分配約定電量。"""
    dataset = Dataset(
        wind_farms=[make_farm(generation=1000.0)],
        companies=[make_company(consumption=1000.0)],
        contracts=[make_contract(alloc=AllocationType.VOLUME, value=300.0)],
    )
    result = match(dataset)
    assert result.allocations[0].allocated_mwh == pytest.approx(300.0)


def test_oversubscription_is_curtailed_proportionally():
    """需求超過發電量時應等比削減，且總分配等於年發電量。"""
    dataset = Dataset(
        wind_farms=[make_farm(generation=1000.0)],
        companies=[
            make_company(id="co1", consumption=1000.0),
            make_company(id="co2", consumption=1000.0),
        ],
        contracts=[
            # 需求 800 + 400 = 1200 > 1000 → scale = 1000/1200
            make_contract(
                id="ct1", company_id="co1",
                alloc=AllocationType.VOLUME, value=800.0,
            ),
            make_contract(
                id="ct2", company_id="co2",
                alloc=AllocationType.VOLUME, value=400.0,
            ),
        ],
    )
    result = match(dataset)
    a1 = next(a for a in result.allocations if a.contract_id == "ct1")
    a2 = next(a for a in result.allocations if a.contract_id == "ct2")
    assert a1.allocated_mwh == pytest.approx(1000 * 800 / 1200)
    assert a2.allocated_mwh == pytest.approx(1000 * 400 / 1200)
    assert a1.curtailed and a2.curtailed
    total = a1.allocated_mwh + a2.allocated_mwh
    assert total == pytest.approx(1000.0)


def test_surplus_when_undersubscribed(simple_dataset):
    """只認購 50% 時，案場應有 50% 剩餘綠電。"""
    result = match(simple_dataset)
    farm = result.wind_farm_results[0]
    assert farm.allocated_mwh == pytest.approx(500.0)
    assert farm.surplus_mwh == pytest.approx(500.0)
    assert farm.utilization_ratio == pytest.approx(0.5)
    assert farm.oversubscribed is False


def test_company_re_coverage_and_gap():
    """企業覆蓋率與 RE 目標缺口計算。"""
    dataset = Dataset(
        wind_farms=[make_farm(generation=1000.0)],
        # 用電 1000、RE100 → 目標 1000；只拿到 400 → 缺口 600
        companies=[make_company(consumption=1000.0, target=1.0)],
        contracts=[make_contract(alloc=AllocationType.VOLUME, value=400.0)],
    )
    result = match(dataset)
    c = result.company_results[0]
    assert c.allocated_mwh == pytest.approx(400.0)
    assert c.coverage_ratio == pytest.approx(0.4)
    assert c.re_target_mwh == pytest.approx(1000.0)
    assert c.target_gap_mwh == pytest.approx(600.0)
    assert c.target_met is False


def test_company_meets_target():
    """分配量達到 RE 目標時 target_met 為 True、缺口為 0。"""
    dataset = Dataset(
        wind_farms=[make_farm(generation=1000.0)],
        companies=[make_company(consumption=1000.0, target=0.5)],
        contracts=[make_contract(alloc=AllocationType.VOLUME, value=600.0)],
    )
    result = match(dataset)
    c = result.company_results[0]
    assert c.target_gap_mwh == pytest.approx(0.0)
    assert c.target_met is True


def test_company_with_no_contract_has_zero_allocation():
    dataset = Dataset(
        wind_farms=[make_farm(generation=1000.0)],
        companies=[make_company(id="co-idle", consumption=500.0, target=1.0)],
        contracts=[],
    )
    result = match(dataset)
    c = result.company_results[0]
    assert c.allocated_mwh == 0.0
    assert c.coverage_ratio == 0.0
    assert c.target_gap_mwh == pytest.approx(500.0)


def test_summary_aggregation(simple_dataset):
    result = match(simple_dataset)
    s = result.summary
    assert s.total_generation_mwh == pytest.approx(1000.0)
    assert s.total_allocated_mwh == pytest.approx(500.0)
    assert s.total_surplus_mwh == pytest.approx(500.0)
    assert s.utilization_ratio == pytest.approx(0.5)
    assert s.company_count == 1
    assert s.companies_meeting_target == 0


def test_unknown_farm_reference_raises():
    dataset = Dataset(
        wind_farms=[make_farm(id="wf1")],
        companies=[make_company(id="co1")],
        contracts=[make_contract(farm_id="ghost")],
    )
    with pytest.raises(ValueError, match="不存在的案場"):
        match(dataset)


def test_unknown_company_reference_raises():
    dataset = Dataset(
        wind_farms=[make_farm(id="wf1")],
        companies=[make_company(id="co1")],
        contracts=[make_contract(company_id="ghost")],
    )
    with pytest.raises(ValueError, match="不存在的企業"):
        match(dataset)


def test_ratio_value_out_of_range_rejected():
    """ratio 合約 value > 1 應在模型驗證階段被拒絕。"""
    with pytest.raises(ValueError):
        make_contract(alloc=AllocationType.RATIO, value=1.5)
