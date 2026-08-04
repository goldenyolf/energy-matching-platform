"""upsert 語意：重複匯入是更新或 no-op，不是靜默略過，也不是複製一份。"""

from __future__ import annotations

from app.ingestion import csv_importer
from app.models import Battery, Contract, Customer, GenerationData, Meter, WindFarm

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
    """外鍵查無資料要點名是哪個欄位，不是丟一串英文例外文字。

    代碼本身進 sample_value，不進 message——這樣兩列不同的查無代碼還是能收斂
    成同一組「案場代碼對應不到」，而不是各自變成一則獨立訊息。
    """
    csv = (
        "wind_farm_code,period_start,period_end,generated_energy_mwh\n"
        "WF-NOPE,2026-01-01,2026-01-31,1000\n"
    )
    result = csv_importer.import_generation(db, _rows(csv))

    assert result.imported == 0
    assert "案場代碼" in result.error_groups[0].message
    assert result.error_groups[0].sample_value == "WF-NOPE"


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


def test_meter_blank_name_on_reimport_does_not_overwrite_with_the_code(db):
    """名稱沒填只在「新建」時沿用代碼兜底——既有列的空白仍然是「不動」。

    build() 泛化跑過整個 spec，若兜底邏輯誤放在那裡，會連 update 路徑都套用，
    把已經取好的名稱洗回代碼本身。
    """
    db.add(Customer(code="CUS-M2", company_name="M2 電力"))
    db.commit()
    csv = "customer_code,code,name,re_target_percent\nCUS-M2,MTR-U2,一廠,50\n"
    csv_importer.import_meters(db, _rows(csv))
    assert db.query(Meter).one().name == "一廠"

    blank_name = "customer_code,code,name,re_target_percent\nCUS-M2,MTR-U2,,80\n"
    result = csv_importer.import_meters(db, _rows(blank_name))

    assert result.updated == 1
    assert result.sample_rows[0].changed == ["re_target_percent"]
    meter = db.query(Meter).one()
    assert meter.name == "一廠"
    assert meter.re_target_percent == 80


def test_battery_blank_name_on_reimport_does_not_overwrite_with_the_code(db):
    db.add(Customer(code="CUS-B2", company_name="B2 電力"))
    db.commit()
    csv = (
        "customer_code,code,name,energy_capacity_mwh,power_mw\n"
        "CUS-B2,BAT-U2,儲能一,20,5\n"
    )
    csv_importer.import_batteries(db, _rows(csv))
    assert db.query(Battery).one().name == "儲能一"

    blank_name = (
        "customer_code,code,name,energy_capacity_mwh,power_mw\n" "CUS-B2,BAT-U2,,40,5\n"
    )
    result = csv_importer.import_batteries(db, _rows(blank_name))

    assert result.updated == 1
    assert result.sample_rows[0].changed == ["energy_capacity_mwh"]
    battery = db.query(Battery).one()
    assert battery.name == "儲能一"
    assert battery.energy_capacity_mwh == 40


def test_many_bad_rows_in_one_column_collapse_to_a_single_group(db):
    """兩千列同一欄格式錯，使用者要看到的是「這一欄整欄格式錯了」一則發現，
    不是兩千則長得幾乎一樣的訊息——這是分組設計的整個理由。"""
    header = "code,name,installed_capacity_mw\n"
    # 每一列的裝置容量都不一樣（千分位逗號格式錯，CSV 欄位用引號包起來讓逗號留在
    # 值裡而不是被當成分隔符），確認分組看的是「原因」不是「值」——原值不同
    # 不該讓它們變成不同組。
    bad_rows = "\n".join(f'WF-BAD{i},名稱{i},"1,{i}00"' for i in range(5))
    result = csv_importer.import_wind_farms(db, _rows(header + bad_rows + "\n"))

    assert result.imported == 0
    assert len(result.error_groups) == 1
    group = result.error_groups[0]
    assert group.count == 5
    assert group.field == "installed_capacity_mw"
    assert "不是數字" in group.message
    assert "1,000" not in group.message and "1,100" not in group.message


def test_error_rows_are_included_in_the_row_preview(db):
    """RowResult.action 宣告了 "error"，錯誤列也該進 sample_rows 讓 UI 能逐列顯示
    ——不是只有 error_groups 這個整檔彙總。"""
    csv = "code,name,installed_capacity_mw\nWF-OK1,好名字,100\nWF-BAD1,壞名字,abc\n"
    result = csv_importer.import_wind_farms(db, _rows(csv))

    assert [r.action for r in result.sample_rows] == ["create", "error"]
    error_row = result.sample_rows[1]
    assert error_row.key == "WF-BAD1"
    assert error_row.message is not None and "不是數字" in error_row.message


def test_pydantic_validation_errors_are_chinese_and_grouped(db):
    """create() 交給 pydantic 驗證的錯誤（如超出 0-100 的比例）也要是中文，
    而且不能把 pydantic 的原始英文文字（含 input_value=...）洩漏出來，
    否則同一種錯誤會因為值不同而拆成一堆各自一則的組。"""
    csv = (
        "code,company_name,re_target_percent\n"
        "CUS-V1,甲公司,150\n"
        "CUS-V2,乙公司,999\n"
    )
    result = csv_importer.import_customers(db, _rows(csv))

    assert result.imported == 0
    assert len(result.error_groups) == 1
    group = result.error_groups[0]
    assert group.count == 2
    assert group.field == "re_target_percent"
    assert "RE 目標" in group.message
    assert "小於等於 100" in group.message
    assert "input_value" not in group.message
    assert "validation error" not in group.message.lower()


def test_battery_blank_capacity_on_a_new_row_is_a_chinese_error_not_a_crash(db):
    """BatteryCreate.energy_capacity_mwh / power_mw 是沒有預設值的必填欄；
    範本產出的欄位表如果沒把它們標成 required，空白會直接讓 pydantic 丟一則
    英文 Field required 出來，而不是我們自己的中文必填訊息。"""
    db.add(Customer(code="CUS-B3", company_name="B3 電力"))
    db.commit()
    csv = (
        "customer_code,code,name,energy_capacity_mwh,power_mw\nCUS-B3,BAT-U3,儲能三,,\n"
    )

    result = csv_importer.import_batteries(db, _rows(csv))

    assert result.imported == 0
    assert db.query(Battery).count() == 0
    messages = " ".join(g.message for g in result.error_groups)
    assert "必填" in messages
    assert "validation error" not in messages.lower()


def test_update_path_validates_through_the_create_model(db):
    """upsert 是新語意：update() 不能因為只是 setattr 就繞過驗證——不然重新
    匯入可以把既有列的 re_target_percent 改成 150，這在新建列是擋得住的，
    不能在既有列上就放行。"""
    csv = "code,company_name,re_target_percent\nCUS-V3,甲公司,50\n"
    csv_importer.import_customers(db, _rows(csv))
    assert db.query(Customer).one().re_target_percent == 50

    bad = "code,company_name,re_target_percent\nCUS-V3,甲公司,150\n"
    result = csv_importer.import_customers(db, _rows(bad))

    assert result.updated == 0
    assert result.imported == 0
    assert len(result.error_groups) == 1
    assert db.query(Customer).one().re_target_percent == 50


def test_contract_update_cannot_make_end_date_precede_start_date(db):
    """跨欄位的業務規則（end_date 不能早於 start_date）只掛在 ContractCreate 的
    model_validator 上；bare setattr 完全不會跑到它，所以要靠 update() 自己
    先組出合併後的完整狀態，過一次 ContractCreate 才能擋下來。"""
    csv_importer.import_wind_farms(
        db, _rows("code,name,installed_capacity_mw\nWF-V1,V1,10\n")
    )
    csv_importer.import_customers(db, _rows("code,company_name\nCUS-V4,V4\n"))
    contract_csv = (
        "contract_number,wind_farm_code,customer_code,start_date,end_date,"
        "contracted_percentage\nPPA-V1,WF-V1,CUS-V4,2026-01-01,2026-12-31,50\n"
    )
    csv_importer.import_contracts(db, _rows(contract_csv))
    assert db.query(Contract).one().end_date.isoformat() == "2026-12-31"

    bad_dates = (
        "contract_number,wind_farm_code,customer_code,start_date,end_date,"
        "contracted_percentage\nPPA-V1,WF-V1,CUS-V4,2026-01-01,2025-12-31,50\n"
    )
    result = csv_importer.import_contracts(db, _rows(bad_dates))

    assert result.updated == 0
    assert len(result.error_groups) == 1
    assert "結束日不能早於起始日" in result.error_groups[0].message
    assert db.query(Contract).one().end_date.isoformat() == "2026-12-31"


def test_wrong_header_with_zero_data_rows_still_reports_the_header_error(db):
    """標題全錯、資料列因此一列都讀不出來的檔案，不能因為 rows 是空的就放行——
    那樣使用者只會看到「匯入成功、0 筆」，比報錯更誤導。"""
    csv = "not_a_real_column,also_wrong\n"  # 標題錯，沒有任何資料列
    result = csv_importer.import_wind_farms(db, _rows(csv))

    assert result.total_rows == 0
    assert len(result.error_groups) == 1
    assert "缺少必填欄位" in result.error_groups[0].message


def test_dry_run_matches_the_real_import_for_updates_and_skips(db):
    """Dry-run 最容易漏測的是 update／skip：它們會動到 ORM 狀態（setattr／
    flush），dry_run_session 退回去之後這些改動必須完全消失，後面真正 commit
    的那次結果還要跟預覽一致。"""
    csv_importer.import_wind_farms(db, _rows(FARM_CSV))

    preview_update = csv_importer.import_wind_farms(
        db, _rows(FARM_CSV_RENAMED), dry_run=True
    )
    assert db.query(WindFarm).one().name == "原始名稱"  # 預覽沒有真的寫入
    real_update = csv_importer.import_wind_farms(db, _rows(FARM_CSV_RENAMED))
    assert (
        preview_update.imported,
        preview_update.updated,
        preview_update.skipped,
    ) == (
        real_update.imported,
        real_update.updated,
        real_update.skipped,
    )
    assert db.query(WindFarm).one().name == "改過的名稱"

    preview_skip = csv_importer.import_wind_farms(
        db, _rows(FARM_CSV_RENAMED), dry_run=True
    )
    real_skip = csv_importer.import_wind_farms(db, _rows(FARM_CSV_RENAMED))
    assert (preview_skip.imported, preview_skip.updated, preview_skip.skipped) == (
        real_skip.imported,
        real_skip.updated,
        real_skip.skipped,
    )
    assert (preview_skip.imported, preview_skip.updated, preview_skip.skipped) == (
        0,
        0,
        1,
    )
    # dry-run 的 update／skip 不該留下任何殘跡：既有列的欄位值仍是真正 commit
    # 過的那個版本，不是預覽路徑 setattr 之後沒退乾淨的髒狀態。
    assert db.query(WindFarm).one().name == "改過的名稱"
