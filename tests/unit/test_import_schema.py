"""欄位表是單一真相：它宣告的欄位必須真的被 importer 讀到。"""

from __future__ import annotations

import inspect

import pytest

from app.ingestion import csv_importer
from app.ingestion.schema import SPECS

# spec 的 entity → csv_importer 裡對應的函式
IMPORTERS = {
    "farm": csv_importer.import_wind_farms,
    "customer": csv_importer.import_customers,
    "meter": csv_importer.import_meters,
    "battery": csv_importer.import_batteries,
    "contract": csv_importer.import_contracts,
    "generation": csv_importer.import_generation,
    "consumption": csv_importer.import_consumption,
}


def test_every_entity_has_an_importer():
    assert set(SPECS) == set(IMPORTERS)


@pytest.mark.parametrize("entity", sorted(SPECS))
def test_declared_columns_are_actually_read(entity):
    """防止 IMPORT_COLS 那種漂移：宣告了卻沒人讀 = 騙使用者。"""
    source = inspect.getsource(IMPORTERS[entity])
    missing = [c.name for c in SPECS[entity].columns if c.name not in source]
    assert not missing, f"{entity} 宣告了但 importer 沒讀: {missing}"


@pytest.mark.parametrize("entity", sorted(SPECS))
def test_natural_key_columns_are_declared(entity):
    spec = SPECS[entity]
    declared = set(spec.column_names())
    assert set(spec.natural_key) <= declared


@pytest.mark.parametrize("entity", sorted(SPECS))
def test_every_column_has_chinese_label_and_example(entity):
    for col in SPECS[entity].columns:
        assert col.label, f"{entity}.{col.name} 缺中文說明"
        assert col.example, f"{entity}.{col.name} 缺範本示範值"


def test_contract_exposes_the_depth_fields():
    """這四個欄位存在於 importer 卻從沒出現在 UI，是本次要修的問題之一。"""
    names = set(SPECS["contract"].column_names())
    assert {
        "monthly_shares",
        "min_offtake_percent",
        "price_escalation_percent",
        "price_base_year",
    } <= names


def test_farm_exposes_the_engineering_fields():
    names = set(SPECS["farm"].column_names())
    assert {
        "farm_type",
        "capacity_factor_percent",
        "p90_capacity_factor_percent",
        "turbine_count",
        "grid_connection_voltage",
    } <= names
