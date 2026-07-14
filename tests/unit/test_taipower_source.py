"""Unit tests for the Taipower wind open-data adapter.

Uses a small in-memory CSV fixture that mirrors the real dataset schema
(dataset 29961). No real network is touched — the fetch path is monkeypatched.

The adapter imports a rolling window of the most recent N months *present in the
data* (default 12), which may span calendar-year boundaries.
"""

from __future__ import annotations

import pytest

from app.ingestion.taipower import TaipowerWindSource

CSV_HEADER = (
    "年度/Year,月份/Month,縣市/County(/City),縣市別代碼/CountyCode,"
    "發電站名稱/Station Name,風機編號/Wind Turbine Number,"
    "裝置容量(kW)/Installed Capacity(kW),"
    "風機發電量(度)/Wind Turbine Power Generation(kW),"
    "風機發電時數(小時)/Wind Turbine Power Generation Hour(hr),"
    "風機未發電時數(小時)/Wind Turbine Without Power Generation Hour(hr)"
)

TEST_STATION = "測試風電站/Test Wind Power Station"
OTHER_STATION = "另一風電站/Other Wind Power Station"
TEST_COUNTY = "測試縣/Test County"
OTHER_COUNTY = "別的縣/Other County"


def _row(year, month, county, code, station, turbine, cap, gen):
    # Trailing 0,0 = generation/non-generation hours (unused by the adapter).
    return f"{year},{month},{county},{code},{station},{turbine},{cap},{gen},0,0"


# TEST station has 5 distinct months (2024-02 back to 2023-10); OTHER has 1.
# Newest→oldest for TEST: 2024-02, 2024-01, 2023-12, 2023-11, 2023-10.
#   2024-02: partial "-" (#2 missing)   2023-11: all "-" (no generation)
#   2023-10: oldest, dropped by a 4-month window
CSV_ROWS = [
    _row("2024", "02", TEST_COUNTY, "99000", TEST_STATION, "#1", "100", "500000"),
    _row("2024", "02", TEST_COUNTY, "99000", TEST_STATION, "#2", "100", "-"),
    _row("2024", "01", TEST_COUNTY, "99000", TEST_STATION, "#1", "100", "1000000"),
    _row("2024", "01", TEST_COUNTY, "99000", TEST_STATION, "#2", "100", "2000000"),
    _row("2023", "12", TEST_COUNTY, "99000", TEST_STATION, "#1", "100", "400000"),
    _row("2023", "12", TEST_COUNTY, "99000", TEST_STATION, "#2", "100", "300000"),
    _row("2023", "11", TEST_COUNTY, "99000", TEST_STATION, "#1", "100", "-"),
    _row("2023", "10", TEST_COUNTY, "99000", TEST_STATION, "#1", "100", "9999999"),
    _row("2024", "02", OTHER_COUNTY, "88000", OTHER_STATION, "#1", "50", "3000000"),
]


@pytest.fixture
def csv_file(tmp_path):
    """Write the fixture CSV (with a UTF-8 BOM, like the real file) to disk."""
    path = tmp_path / "wind_turbines.csv"
    content = CSV_HEADER + "\n" + "\n".join(CSV_ROWS) + "\n"
    path.write_bytes(("﻿" + content).encode("utf-8"))
    return path


@pytest.fixture
def source(csv_file):
    # 4-month window → 2024-02, 2024-01, 2023-12, 2023-11 (drops 2023-10).
    return TaipowerWindSource(months=4, csv_path=csv_file)


def _by_code(rows):
    return {r["code"]: r for r in rows}


def _gen_index(rows):
    return {(r["wind_farm_code"], r["period_start"]): r for r in rows}


def test_wind_farms_dedupe_stations_and_sum_capacity(source):
    farms = _by_code(source.wind_farms())

    assert set(farms) == {"TPC-TEST", "TPC-OTHER"}

    test = farms["TPC-TEST"]
    assert test["name"] == "測試風電站/Test Wind Power Station"
    assert test["location"] == "測試縣/Test County"
    assert test["operator_name"] == "台灣電力公司"
    assert test["status"] == "operational"
    # Two distinct turbines, 100 kW each → 0.2 MW (not summed per row/month).
    assert float(test["installed_capacity_mw"]) == pytest.approx(0.2)

    assert float(farms["TPC-OTHER"]["installed_capacity_mw"]) == pytest.approx(0.05)


def test_generation_aggregates_turbines_and_converts_to_mwh(source):
    gen = _gen_index(source.generation())

    # Jan Test = 1,000,000 + 2,000,000 度 = 3,000,000 kWh = 3000 MWh.
    jan = gen[("TPC-TEST", "2024-01-01")]
    assert jan["period_end"] == "2024-01-31"
    assert float(jan["generated_energy_mwh"]) == pytest.approx(3000.0)
    assert jan["data_source"] == "taipower"


def test_period_end_uses_month_last_day_leap_year(source):
    gen = _gen_index(source.generation())
    # Feb 2024 is a leap year → 29 days. Only #1 (500,000) counts; #2 is "-".
    feb = gen[("TPC-TEST", "2024-02-01")]
    assert feb["period_end"] == "2024-02-29"
    assert float(feb["generated_energy_mwh"]) == pytest.approx(500.0)


def test_window_spans_year_boundary(source):
    gen = _gen_index(source.generation())
    # The window reaches back into the previous year.
    dec = gen[("TPC-TEST", "2023-12-01")]
    assert dec["period_end"] == "2023-12-31"
    assert float(dec["generated_energy_mwh"]) == pytest.approx(700.0)


def test_generation_skips_all_missing_month(source):
    gen = _gen_index(source.generation())
    # 2023-11 has only "-" values → no generation row emitted at all.
    assert ("TPC-TEST", "2023-11-01") not in gen


def test_window_drops_months_older_than_n(source):
    gen = source.generation()
    # 2023-10 (the 9,999,999 row) is outside the 4-month window → excluded.
    assert not any(r["period_start"] == "2023-10-01" for r in gen)
    assert not any(float(r["generated_energy_mwh"]) > 9000 for r in gen)


def test_default_window_is_twelve_months_includes_all_fixture(csv_file):
    # Only 5 distinct months exist (< 12), so the default window keeps them all,
    # including the oldest 2023-10.
    src = TaipowerWindSource(csv_path=csv_file)
    gen = _gen_index(src.generation())
    assert ("TPC-TEST", "2023-10-01") in gen
    oct_mwh = float(gen[("TPC-TEST", "2023-10-01")]["generated_energy_mwh"])
    assert oct_mwh == pytest.approx(9999.999)


def test_demand_side_methods_are_empty(source):
    assert source.customers() == []
    assert source.contracts() == []
    assert source.consumption() == []


def test_missing_local_file_raises_clear_error(tmp_path):
    src = TaipowerWindSource(months=12, csv_path=tmp_path / "does_not_exist.csv")
    with pytest.raises(FileNotFoundError) as exc:
        src.wind_farms()
    assert "--fetch" in str(exc.value)


def test_fetch_path_uses_http_get(monkeypatch, csv_file):
    captured = {}

    def fake_get(url: str) -> bytes:
        captured["url"] = url
        return csv_file.read_bytes()

    monkeypatch.setattr("app.ingestion.taipower._http_get", fake_get)
    src = TaipowerWindSource(months=4, fetch=True, url="https://example.test/wind.csv")

    farms = _by_code(src.wind_farms())
    assert set(farms) == {"TPC-TEST", "TPC-OTHER"}
    assert captured["url"] == "https://example.test/wind.csv"
