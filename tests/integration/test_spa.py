"""Smoke tests for the static SPA serving + cache-busting (no browser needed)."""

from __future__ import annotations


def test_root_redirects_to_app(client):
    r = client.get("/", follow_redirects=False)
    assert r.status_code in (307, 308)
    assert r.headers["location"] == "/app/"


def test_spa_index_uncached_with_versioned_assets(client):
    r = client.get("/app/")
    assert r.status_code == 200
    assert "no-cache" in r.headers.get("cache-control", "")
    body = r.text
    assert "綠電媒合平台" in body  # the app shell rendered
    # assets are cache-busted with a content-hash ?v=… (the bug the user hit)
    assert "app.js?v=" in body
    assert "styles.css?v=" in body


def test_spa_assets_served_immutable(client):
    for asset in ("app.js", "api.js", "styles.css"):
        r = client.get(f"/app/{asset}")
        assert r.status_code == 200, asset
        assert "max-age=31536000" in r.headers.get("cache-control", ""), asset
