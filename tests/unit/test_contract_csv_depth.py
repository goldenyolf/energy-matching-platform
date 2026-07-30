"""合約深化欄位的 CSV 匯入（月別配比／take-or-pay／CPI 年漲幅）。

這些條款引擎本來就會用（月上限、結算的保證量差額、逐年價格），但匯入器一直沒讀，
所以示範資料一格都填不進來。這裡釘住「CSV 有寫就進得去、沒寫就是 None」。
"""

from __future__ import annotations

import pytest

from app.ingestion import csv_importer
from app.models import Contract, Customer, WindFarm

WIND_SHAPE = "1.35;1.25;1.05;0.85;0.70;0.55;0.55;0.60;0.85;1.15;1.30;1.40"


@pytest.fixture()
def pair(db):
    db.add(WindFarm(code="F1", name="風場一", installed_capacity_mw=100))
    db.add(Customer(code="K1", company_name="用電廠一"))
    db.commit()


def _row(**kw) -> dict:
    base = {
        "contract_number": "PPA-T-1",
        "wind_farm_code": "F1",
        "customer_code": "K1",
        "start_date": "2024-01-01",
        "end_date": "2030-12-31",
        "contracted_energy_mwh": "12000",
        "contracted_percentage": "",
        "price_per_kwh": "4.5",
        "priority": "1",
        "status": "active",
    }
    base.update(kw)
    return base


def test_depth_columns_are_imported(db, pair):
    res = csv_importer.import_contracts(
        db,
        [
            _row(
                monthly_shares=WIND_SHAPE,
                min_offtake_percent="80",
                price_escalation_percent="2.5",
                price_base_year="2024",
            )
        ],
    )
    assert res.imported == 1 and not res.errors

    c = db.query(Contract).one()
    assert c.monthly_shares == [
        1.35,
        1.25,
        1.05,
        0.85,
        0.70,
        0.55,
        0.55,
        0.60,
        0.85,
        1.15,
        1.30,
        1.40,
    ]
    assert c.min_offtake_percent == 80.0
    assert c.price_escalation_percent == 2.5
    assert c.price_base_year == 2024


def test_blank_depth_columns_stay_none(db, pair):
    csv_importer.import_contracts(
        db,
        [
            _row(
                monthly_shares="",
                min_offtake_percent="",
                price_escalation_percent="",
                price_base_year="",
            )
        ],
    )
    c = db.query(Contract).one()
    assert c.monthly_shares is None
    assert c.min_offtake_percent is None
    assert c.price_escalation_percent is None
    assert c.price_base_year is None


def test_missing_depth_columns_are_fine(db, pair):
    """舊的 CSV（沒有這幾欄）必須照樣匯得進來。"""
    res = csv_importer.import_contracts(db, [_row()])
    assert res.imported == 1 and not res.errors
    assert db.query(Contract).one().monthly_shares is None


def test_a_bad_monthly_shape_is_reported_not_silently_dropped(db, pair):
    res = csv_importer.import_contracts(db, [_row(monthly_shares="1.0;2.0;3.0")])
    assert res.imported == 0
    assert res.errors and "12" in res.errors[0]
    assert db.query(Contract).count() == 0


def test_sample_data_exercises_every_depth_clause(seeded_db):
    """示範資料要真的用到這三種條款,否則畫面上全是「–」,等於沒做。"""
    cs = list(seeded_db.query(Contract))
    assert any(c.monthly_shares for c in cs), "應有合約使用月別配比"
    assert any(c.min_offtake_percent is not None for c in cs), "應有合約帶 take-or-pay"
    assert any(
        c.price_escalation_percent is not None for c in cs
    ), "應有合約帶 CPI 年漲幅"
