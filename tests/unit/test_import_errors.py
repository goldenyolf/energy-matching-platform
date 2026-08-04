"""解析錯誤必須指得出欄位、原值，並且是中文。"""

from __future__ import annotations

import pytest

from app.ingestion import parsing as p
from app.ingestion.schema import SPECS


def test_bad_float_names_the_column_in_chinese():
    col = SPECS["farm"].column("installed_capacity_mw")
    with pytest.raises(p.CellError) as exc:
        p.parse_cell(col, "abc")
    err = exc.value
    assert err.field == "installed_capacity_mw"
    assert err.value == "abc"
    assert "裝置容量" in err.reason
    assert "不是數字" in err.reason


def test_bad_date_says_the_expected_format():
    col = SPECS["contract"].column("start_date")
    with pytest.raises(p.CellError) as exc:
        p.parse_cell(col, "03/07/2026")
    assert "YYYY-MM-DD" in exc.value.reason


def test_blank_optional_cell_is_none():
    col = SPECS["farm"].column("turbine_count")
    assert p.parse_cell(col, "   ") is None


def test_blank_required_cell_is_an_error():
    col = SPECS["farm"].column("code")
    with pytest.raises(p.CellError) as exc:
        p.parse_cell(col, "")
    assert "必填" in exc.value.reason


def test_shares_parses_semicolon_weights():
    col = SPECS["contract"].column("monthly_shares")
    assert p.parse_cell(col, "1;2;3") == [1.0, 2.0, 3.0]
