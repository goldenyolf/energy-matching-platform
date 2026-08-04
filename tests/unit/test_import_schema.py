"""欄位表是單一真相：它宣告的欄位必須真的被 importer 讀到、寫進去。"""

from __future__ import annotations

import pytest
from sqlalchemy import inspect as sa_inspect

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
# 一層，委派給共用管線＋這裡的 handler。
HANDLERS = {
    "farm": csv_importer._FarmHandler,
    "customer": csv_importer._CustomerHandler,
    "meter": csv_importer._MeterHandler,
    "battery": csv_importer._BatteryHandler,
    "contract": csv_importer._ContractHandler,
    "generation": csv_importer._GenerationHandler,
    "consumption": csv_importer._ConsumptionHandler,
}


def test_every_entity_has_an_importer():
    assert set(SPECS) == set(IMPORTERS) == set(HANDLERS)


@pytest.mark.parametrize("entity", sorted(SPECS))
def test_declared_columns_are_actually_consumed(entity):
    """防止 IMPORT_COLS 那種漂移：宣告了卻沒地方接 = 騙使用者。

    handler.build() 是泛化地跑過 ``self.spec.columns`` 讀取的——「原始碼裡有沒有
    出現這個欄名的字面量」不再是有意義的訊號，因為泛化迴圈本來就不會逐一提到
    每個欄名。真正有意義的問題是「讀到之後，create()／update() 接不接得住」：
    這兩條路徑分別要看目標 pydantic ``*Create`` model 有沒有這個欄位、以及 ORM
    model 有沒有這個 mapped column（外鍵欄位如 customer_code 改用它在
    ``_fk_specs`` 裡宣告要轉成的 payload 欄位，如 customer_id，來比對）。
    只要兩邊有一邊接不住，這欄實質上就是宣告了但沒用——不管 build() 有沒有讀到它。
    """
    handler = HANDLERS[entity]()
    create_fields = set(handler.create_model.model_fields)
    orm_columns = {c.key for c in sa_inspect(handler.model).mapper.column_attrs}
    fk_targets = {
        csv_col: payload_field for csv_col, _, payload_field, _ in handler._fk_specs
    }

    missing = []
    for col in SPECS[entity].columns:
        target = fk_targets.get(col.name, col.name)
        if target not in create_fields or target not in orm_columns:
            missing.append(col.name)
    assert not missing, f"{entity} 宣告了但 create()/update() 接不到: {missing}"


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
