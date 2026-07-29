"""Unit tests for the Taipower real-time renewables client.

Instantaneous MW snapshot (dataset 8931) — parsed, not persisted. No network is
touched; the HTTP fetch is injected.
"""

from __future__ import annotations

import json

import pytest

from app.ingestion.taipower_live import LIVE_URL, LiveClient, _num, parse_live


def _unit(unit_type, name, cap, net, ratio="", note=" "):
    return {
        "機組類型": unit_type,
        "機組名稱": name,
        "裝置容量(MW)": cap,
        "淨發電量(MW)": net,
        "淨發電量/裝置容量比(%)": ratio,
        "備註": note,
    }


FIXTURE = {
    "DateTime": "2026-07-16T00:10:00",
    "aaData": [
        _unit("燃氣", "大潭CC#1", "742.7", "692.6"),
        _unit("風力", "彰工", "86.2", "5.7", "6.612%", "部分檢修"),
        _unit("風力", "台中港", "35.0", "3.0", "8.571%"),
        _unit("風力", "觀園", "30.0", "-", "-"),  # missing net
        # 註10 units: Taipower withholds the capacity, so no ratio either
        _unit("風力", "龍B風(註10)", "-", "3.1", "-"),
        _unit("風力", "小計(註5)", "3850.0(6.238%)", "1893.6(5.958%)"),  # subtotal row
        _unit("太陽能", "太陽能彙總", "1000.0", "120.5"),
        _unit("水力", "德基", "234.0", "50.0"),
        _unit("儲能", "儲能彙總", "3850.0(6.238%)", "100.0"),  # excluded + noisy cap
    ],
}

FIXTURE_BYTES = json.dumps(FIXTURE, ensure_ascii=False).encode("utf-8")


def test_num_handles_noise_and_missing():
    assert _num("742.7") == 742.7
    assert _num("3850.0(6.238%)") == 3850.0  # trailing (…) stripped
    assert _num("-") is None
    assert _num("") is None
    assert _num("N/A") is None
    assert _num(None) is None


def test_parse_live_extracts_wind_units():
    snap = parse_live(FIXTURE)
    assert snap.snapshot_time == "2026-07-16T00:10:00"
    names = {u.name: u for u in snap.wind}
    assert set(names) == {"彰工", "台中港", "觀園", "龍B風(註10)"}
    assert names["彰工"].net_mw == pytest.approx(5.7)
    assert names["彰工"].capacity_mw == pytest.approx(86.2)
    assert names["觀園"].net_mw is None  # "-" → missing


def test_parse_live_carries_output_ratio_and_note():
    # Every per-unit column Taipower publishes reaches the API unchanged.
    names = {u.name: u for u in parse_live(FIXTURE).wind}
    assert names["彰工"].output_ratio_pct == pytest.approx(6.612)
    assert names["彰工"].note == "部分檢修"
    assert names["台中港"].note is None  # blank cell (" ") → None, not " "
    # 註10 units publish no capacity, hence no ratio
    assert names["龍B風(註10)"].capacity_mw is None
    assert names["龍B風(註10)"].output_ratio_pct is None


def test_parse_live_wind_total_ignores_missing():
    snap = parse_live(FIXTURE)
    # 5.7 + 3.0 + 3.1 (觀園 is "-" → excluded)
    assert snap.wind_total_mw == pytest.approx(11.8)


def test_parse_live_excludes_subtotal_rows():
    # Taipower mixes 小計 (subtotal) aggregate rows into the per-unit list; summing
    # them would double-count. They must not appear as units nor in totals.
    snap = parse_live(FIXTURE)
    assert all("小計" not in u.name for u in snap.wind)
    wind_summary = next(s for s in snap.renewable_summary if s.unit_type == "風力")
    assert wind_summary.unit_count == 4  # the subtotal row is not counted
    assert snap.wind_total_mw == pytest.approx(11.8)  # not 11.8 + 1893.6


def test_parse_live_renewable_summary_excludes_storage_and_fossil():
    snap = parse_live(FIXTURE)
    by_type = {s.unit_type: s for s in snap.renewable_summary}
    assert set(by_type) == {"風力", "太陽能", "水力"}  # no 燃氣, no 儲能
    assert by_type["風力"].unit_count == 4
    assert by_type["風力"].net_mw == pytest.approx(11.8)
    assert by_type["太陽能"].net_mw == pytest.approx(120.5)
    assert snap.renewable_total_mw == pytest.approx(11.8 + 120.5 + 50.0)


def test_client_caches_within_ttl_and_refetches_after():
    calls = {"n": 0}
    clock = {"t": 1000.0}

    def fake_get(url: str) -> bytes:
        calls["n"] += 1
        return FIXTURE_BYTES

    client = LiveClient(http_get=fake_get, ttl_seconds=100, clock=lambda: clock["t"])

    client.get()
    client.get()
    assert calls["n"] == 1  # second call served from cache

    clock["t"] += 50
    client.get()
    assert calls["n"] == 1  # still within TTL

    clock["t"] += 100  # now past TTL
    client.get()
    assert calls["n"] == 2

    client.get(force=True)
    assert calls["n"] == 3  # force bypasses cache


def test_client_decodes_utf8_bom():
    def fake_get(url: str) -> bytes:
        return b"\xef\xbb\xbf" + FIXTURE_BYTES  # prepend a UTF-8 BOM

    snap = LiveClient(http_get=fake_get).get()
    assert snap.snapshot_time == "2026-07-16T00:10:00"


def test_client_reports_the_url_it_fetched():
    # The UI links to source_url, so it must be the URL actually fetched.
    snap = LiveClient(http_get=lambda url: FIXTURE_BYTES).get()
    assert snap.source_url == LIVE_URL

    other = "https://example.test/mirror.json"
    snap = LiveClient(url=other, http_get=lambda url: FIXTURE_BYTES).get()
    assert snap.source_url == other
