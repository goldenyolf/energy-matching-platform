"""Unit tests for the Taipower wind open-data adapter.

Uses a small in-memory CSV fixture that mirrors the real dataset schema
(dataset 29961). No real network is touched — the fetch path is monkeypatched.
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


# Test = station with 2 turbines; Other = station with 1 turbine.
# Includes a partial "-" (Feb #2), an all-"-" month (Mar), and a 2023 row.
CSV_ROWS = [
    _row("2024", "01", TEST_COUNTY, "99000", TEST_STATION, "#1", "100", "1000000"),
    _row("2024", "01", TEST_COUNTY, "99000", TEST_STATION, "#2", "100", "2000000"),
    _row("2024", "02", TEST_COUNTY, "99000", TEST_STATION, "#1", "100", "500000"),
    _row("2024", "02", TEST_COUNTY, "99000", TEST_STATION, "#2", "100", "-"),
    _row("2024", "03", TEST_COUNTY, "99000", TEST_STATION, "#1", "100", "-"),
    _row("2023", "01", TEST_COUNTY, "99000", TEST_STATION, "#1", "100", "9999999"),
    _row("2024", "01", OTHER_COUNTY, "88000", OTHER_STATION, "#1", "50", "3000000"),
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
    return TaipowerWindSource(year=2024, csv_path=csv_file)


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


def test_generation_skips_all_missing_month(source):
    gen = _gen_index(source.generation())
    # March has only "-" values → no generation row emitted at all.
    assert ("TPC-TEST", "2024-03-01") not in gen


def test_generation_filters_by_year(source):
    gen = source.generation()
    assert all(r["period_start"].startswith("2024-") for r in gen)
    # The 2023 row (9,999,999) must not leak into any 2024 total.
    assert not any(float(r["generated_energy_mwh"]) > 9000 for r in gen)


def test_demand_side_methods_are_empty(source):
    assert source.customers() == []
    assert source.contracts() == []
    assert source.consumption() == []


def test_missing_local_file_raises_clear_error(tmp_path):
    src = TaipowerWindSource(year=2024, csv_path=tmp_path / "does_not_exist.csv")
    with pytest.raises(FileNotFoundError) as exc:
        src.wind_farms()
    assert "--fetch" in str(exc.value)


def test_fetch_path_uses_http_get(monkeypatch, csv_file):
    captured = {}

    def fake_get(url: str) -> bytes:
        captured["url"] = url
        return csv_file.read_bytes()

    monkeypatch.setattr("app.ingestion.taipower._http_get", fake_get)
    src = TaipowerWindSource(year=2024, fetch=True, url="https://example.test/wind.csv")

    farms = _by_code(src.wind_farms())
    assert set(farms) == {"TPC-TEST", "TPC-OTHER"}
    assert captured["url"] == "https://example.test/wind.csv"
