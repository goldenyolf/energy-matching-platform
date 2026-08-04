"""The static SPA is served same-origin at /app without disturbing the API."""

from __future__ import annotations

import re


def test_spa_index_no_cache_with_versioned_assets(client):
    resp = client.get("/app/")
    assert resp.status_code == 200
    assert resp.headers["cache-control"] == "no-cache"
    # asset references are cache-busted with an 8-char content hash
    assert re.search(r'src="app\.js\?v=[0-9a-f]{8}"', resp.text)
    assert re.search(r'src="api\.js\?v=[0-9a-f]{8}"', resp.text)
    assert re.search(r'href="styles\.css\?v=[0-9a-f]{8}"', resp.text)


def test_spa_js_css_immutable(client):
    for asset in ("/app/app.js", "/app/api.js", "/app/styles.css"):
        cc = client.get(asset).headers["cache-control"]
        assert "immutable" in cc
        assert "max-age=31536000" in cc


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


def test_root_redirects_to_app(client):
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code in (302, 307)
    assert resp.headers["location"] == "/app/"


def test_api_index_advertises_app(client):
    body = client.get("/api").json()
    assert body["app"] == "/app/"


def test_api_still_works(client):
    assert client.get("/health").status_code == 200


def test_import_schema_and_template_are_served(client):
    assert client.get("/api/v1/import/schema").status_code == 200
    assert client.get("/api/v1/import/template/contract").status_code == 200
