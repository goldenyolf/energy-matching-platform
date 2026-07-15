"""GET /api/v1/live/renewables — read-through live view, no network in tests."""

from __future__ import annotations

import json

import pytest

from app.ingestion.taipower_live import LiveClient
from tests.unit.test_taipower_live import FIXTURE_BYTES


@pytest.fixture
def patched_client(monkeypatch):
    """Replace the endpoint's module-level client with an injected fake fetch."""
    import app.api.v1.live as live

    def fake_get(url: str) -> bytes:
        return FIXTURE_BYTES

    monkeypatch.setattr(live, "_client", LiveClient(http_get=fake_get))


def test_live_renewables_returns_snapshot(client, patched_client):
    resp = client.get("/api/v1/live/renewables")
    assert resp.status_code == 200
    body = resp.json()
    assert body["snapshot_time"] == "2026-07-16T00:10:00"
    assert body["wind_total_mw"] == pytest.approx(8.7)
    assert {u["name"] for u in body["wind"]} == {"彰工", "台中港", "觀園"}
    types = {s["unit_type"] for s in body["renewable_summary"]}
    assert types == {"風力", "太陽能", "水力"}


def test_live_renewables_returns_503_on_fetch_error(client, monkeypatch):
    import app.api.v1.live as live

    def boom(url: str) -> bytes:
        raise RuntimeError("upstream down")

    monkeypatch.setattr(live, "_client", LiveClient(http_get=boom))

    resp = client.get("/api/v1/live/renewables")
    assert resp.status_code == 503
    assert "台電" in resp.json()["detail"]


def test_fixture_bytes_are_valid_json():
    # Guard: the shared fixture stays parseable if edited.
    assert json.loads(FIXTURE_BYTES.decode("utf-8"))["DateTime"]
