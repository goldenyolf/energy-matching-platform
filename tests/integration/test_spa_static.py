"""The static SPA is served same-origin at /app without disturbing the API."""

from __future__ import annotations


def test_spa_index_served(client):
    resp = client.get("/app/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert 'id="view"' in resp.text
    assert "綠電媒合平台" in resp.text


def test_spa_assets_served(client):
    css = client.get("/app/styles.css")
    assert css.status_code == 200
    assert "css" in css.headers["content-type"]
    for asset in ("/app/app.js", "/app/api.js"):
        r = client.get(asset)
        assert r.status_code == 200
        assert "javascript" in r.headers["content-type"]


def test_spa_missing_asset_404(client):
    assert client.get("/app/does-not-exist.js").status_code == 404


def test_api_root_advertises_app(client):
    body = client.get("/").json()
    assert body["app"] == "/app/"


def test_api_still_works(client):
    assert client.get("/health").status_code == 200
