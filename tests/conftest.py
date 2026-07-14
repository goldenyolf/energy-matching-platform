"""共用測試資料建構工具。"""

from __future__ import annotations

import pytest

from app.models import (
    AllocationType,
    Company,
    Contract,
    Dataset,
    WindFarm,
)


def make_farm(id="wf1", generation=1000.0, capacity=100.0):
    return WindFarm(
        id=id,
        name=f"Farm {id}",
        location="外海",
        capacity_mw=capacity,
        annual_generation_mwh=generation,
    )


def make_company(id="co1", consumption=1000.0, target=1.0):
    return Company(
        id=id,
        name=f"Company {id}",
        industry="測試",
        annual_consumption_mwh=consumption,
        re_target_ratio=target,
    )


def make_contract(
    id="ct1",
    company_id="co1",
    farm_id="wf1",
    alloc=AllocationType.RATIO,
    value=1.0,
    price=4.5,
    year=2025,
):
    return Contract(
        id=id,
        company_id=company_id,
        wind_farm_id=farm_id,
        allocation_type=alloc,
        value=value,
        price_per_kwh=price,
        start_year=year,
    )


@pytest.fixture
def simple_dataset():
    """1 案場 (1000 MWh) + 1 企業 (用電 1000, RE100) + 1 張 50% ratio 合約。"""
    return Dataset(
        wind_farms=[make_farm(generation=1000.0)],
        companies=[make_company(consumption=1000.0, target=1.0)],
        contracts=[make_contract(value=0.5)],
    )
