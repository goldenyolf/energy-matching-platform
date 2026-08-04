"""欄位表是單一真相：它宣告的欄位必須真的被 importer 讀到。"""

from __future__ import annotations

import inspect
import re

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

# entity → 實際做讀取／寫入的 handler class。Task 4 把每個 import_* 函式改成薄薄
# 一層，委派給共用管線＋這裡的 handler；欄位真正被讀到的地方是 handler，不是
# import_* 本身，所以漂移檢查要看 handler 的原始碼。
HANDLERS = {
    "farm": csv_importer._FarmHandler,
    "customer": csv_importer._CustomerHandler,
    "meter": csv_importer._MeterHandler,
    "battery": csv_importer._BatteryHandler,
    "contract": csv_importer._ContractHandler,
    "generation": csv_importer._GenerationHandler,
    "consumption": csv_importer._ConsumptionHandler,
}

# build() 若含有這個樣式，代表它逐一跑過 spec 宣告的每個欄位（見
# csv_importer._parse_row_cell 的呼叫方式）——這時「有沒有讀到」是結構上保證的，
# 不需要欄位名稱以字面量出現在原始碼裡才算數。
_GENERIC_READ_MARKER = "self.spec.columns"


def test_every_entity_has_an_importer():
    assert set(SPECS) == set(IMPORTERS) == set(HANDLERS)


@pytest.mark.parametrize("entity", sorted(SPECS))
def test_declared_columns_are_actually_read(entity):
    """防止 IMPORT_COLS 那種漂移：宣告了卻沒人讀 = 騙使用者。

    大多數欄位由 handler.build() 泛化地跑過 ``self.spec.columns`` 讀取，這時
    「有沒有讀到」是迴圈結構保證的，不必逐一以字面量出現。改成查代碼再轉 id
    的外鍵欄位（如 customer_code）不在這個迴圈裡，仍要求以字面量出現，跟原本
    一樣嚴格。
    """
    handler = HANDLERS[entity]
    source = inspect.getsource(handler)
    reads_generically = _GENERIC_READ_MARKER in source
    fk_columns = set(getattr(handler, "_fk_columns", ()))

    def _is_read(name: str) -> bool:
        if reads_generically and name not in fk_columns:
            return True
        # Anchor to quoted literals to avoid false positives from substring
        # matches (e.g., 'code' substring of 'customer_code').
        return bool(re.search(rf'["\']{re.escape(name)}["\']', source))

    missing = [c.name for c in SPECS[entity].columns if not _is_read(c.name)]
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
