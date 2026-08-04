"""upsert 語意：重複匯入是更新或 no-op，不是靜默略過，也不是複製一份。"""

from __future__ import annotations

from app.ingestion import csv_importer
from app.models import Battery, Customer, GenerationData, Meter, WindFarm

FARM_CSV = """code,name,installed_capacity_mw
WF-U1,原始名稱,100
"""

FARM_CSV_RENAMED = """code,name,installed_capacity_mw
WF-U1,改過的名稱,100
"""

FARM_CSV_BLANK_NAME = """code,name,installed_capacity_mw
WF-U1,,120
"""


def _rows(text):
    return csv_importer.parse_csv(text)


def test_second_identical_import_is_a_noop_skip(db):
    first = csv_importer.import_wind_farms(db, _rows(FARM_CSV))
    assert (first.imported, first.updated, first.skipped) == (1, 0, 0)

    second = csv_importer.import_wind_farms(db, _rows(FARM_CSV))
    assert (second.imported, second.updated, second.skipped) == (0, 0, 1)
    assert db.query(WindFarm).count() == 1


def test_changed_value_becomes_an_update(db):
    csv_importer.import_wind_farms(db, _rows(FARM_CSV))
    result = csv_importer.import_wind_farms(db, _rows(FARM_CSV_RENAMED))

    assert (result.imported, result.updated, result.skipped) == (0, 1, 0)
    assert result.sample_rows[0].action == "update"
    assert result.sample_rows[0].changed == ["name"]
    assert db.query(WindFarm).one().name == "改過的名稱"


def test_blank_cell_does_not_wipe_an_existing_value(db):
    """Excel 導出常整欄空白，空白＝不動，不是清空。"""
    csv_importer.import_wind_farms(db, _rows(FARM_CSV))
    csv_importer.import_wind_farms(db, _rows(FARM_CSV_BLANK_NAME))

    farm = db.query(WindFarm).one()
    assert farm.name == "原始名稱"
    assert farm.installed_capacity_mw == 120


def test_generation_reimport_does_not_double_the_data(db):
    """匯兩次變兩倍會直接汙染結算金額。"""
    db.add(WindFarm(code="WF-G1", name="G1", installed_capacity_mw=10))
    db.commit()
    gen_csv = """wind_farm_code,period_start,period_end,generated_energy_mwh
WF-G1,2026-01-01,2026-01-31,1000
"""
    csv_importer.import_generation(db, _rows(gen_csv))
    csv_importer.import_generation(db, _rows(gen_csv))

    rows = db.query(GenerationData).all()
    assert len(rows) == 1
    assert rows[0].generated_energy_mwh == 1000


def test_dry_run_matches_the_real_import(db):
    """選後端 dry-run 的整個理由：預覽說什麼，按下去就是什麼。"""
    csv = """code,company_name,annual_consumption_mwh
CUS-D1,甲公司,100
CUS-D2,乙公司,not-a-number
"""
    preview = csv_importer.import_customers(db, _rows(csv), dry_run=True)
    assert db.query(Customer).count() == 0

    real = csv_importer.import_customers(db, _rows(csv))
    assert (preview.imported, preview.updated, preview.skipped) == (
        real.imported,
        real.updated,
        real.skipped,
    )
    assert [g.message for g in preview.error_groups] == [
        g.message for g in real.error_groups
    ]
    assert preview.dry_run is True and real.dry_run is False


def test_missing_required_header_is_one_file_level_error(db):
    """標題列缺必填欄 → 一則整檔錯誤，不是逐列洗版。"""
    csv = "name,installed_capacity_mw\n甲,100\n乙,200\n丙,300\n"
    result = csv_importer.import_wind_farms(db, _rows(csv))

    assert result.imported == 0
    assert len(result.error_groups) == 1
    group = result.error_groups[0]
    assert group.count == 1, "整檔錯誤只該有一則"
    assert group.sample_rows == [1], "指向標題列"
    assert "code" in group.message and "缺少" in group.message


def test_unknown_columns_are_ignored_not_rejected(db):
    """Excel 導出常多欄，多欄不該擋住匯入。"""
    csv = "code,name,installed_capacity_mw,備註,某個空欄\nWF-X1,X1,100,隨便寫,\n"
    result = csv_importer.import_wind_farms(db, _rows(csv))
    assert result.imported == 1
    assert result.error_groups == []


def test_blank_required_field_on_a_new_row_is_an_error(db):
    """空白在既有列上是「不動」，但在全新列上，必填欄位還是必填。"""
    csv = "code,name,installed_capacity_mw\nWF-NEW1,,100\n"
    result = csv_importer.import_wind_farms(db, _rows(csv))

    assert result.imported == 0
    assert len(result.error_groups) == 1
    assert "案場名稱" in result.error_groups[0].message
    assert "必填" in result.error_groups[0].message
    assert db.query(WindFarm).count() == 0


def test_unknown_wind_farm_code_names_the_farm_in_the_error(db):
    """外鍵查無資料要點名是哪個代碼、哪個欄位，不是丟一串英文例外文字。"""
    csv = (
        "wind_farm_code,period_start,period_end,generated_energy_mwh\n"
        "WF-NOPE,2026-01-01,2026-01-31,1000\n"
    )
    result = csv_importer.import_generation(db, _rows(csv))

    assert result.imported == 0
    assert "案場代碼" in result.error_groups[0].message
    assert "WF-NOPE" in result.error_groups[0].message
    assert "不存在" in result.error_groups[0].message


def test_meter_upsert_cycle(db):
    """電號／廠區也走同一套 handler shape：create → skip → update。"""
    db.add(Customer(code="CUS-M1", company_name="M 電力"))
    db.commit()
    csv = "customer_code,code,name,re_target_percent\nCUS-M1,MTR-U1,一廠,50\n"

    first = csv_importer.import_meters(db, _rows(csv))
    assert (first.imported, first.updated, first.skipped) == (1, 0, 0)

    second = csv_importer.import_meters(db, _rows(csv))
    assert (second.imported, second.updated, second.skipped) == (0, 0, 1)
    assert db.query(Meter).count() == 1

    renamed = "customer_code,code,name,re_target_percent\nCUS-M1,MTR-U1,二廠,50\n"
    third = csv_importer.import_meters(db, _rows(renamed))
    assert (third.imported, third.updated, third.skipped) == (0, 1, 0)
    assert db.query(Meter).one().name == "二廠"


def test_battery_upsert_cycle(db):
    """客戶側儲能也走同一套 handler shape：create → skip → update。"""
    db.add(Customer(code="CUS-B1", company_name="B 電力"))
    db.commit()
    csv = (
        "customer_code,code,name,energy_capacity_mwh,power_mw\n"
        "CUS-B1,BAT-U1,儲能一,20,5\n"
    )

    first = csv_importer.import_batteries(db, _rows(csv))
    assert (first.imported, first.updated, first.skipped) == (1, 0, 0)

    second = csv_importer.import_batteries(db, _rows(csv))
    assert (second.imported, second.updated, second.skipped) == (0, 0, 1)
    assert db.query(Battery).count() == 1

    bigger = (
        "customer_code,code,name,energy_capacity_mwh,power_mw\n"
        "CUS-B1,BAT-U1,儲能一,40,5\n"
    )
    third = csv_importer.import_batteries(db, _rows(bigger))
    assert (third.imported, third.updated, third.skipped) == (0, 1, 0)
    assert db.query(Battery).one().energy_capacity_mwh == 40
