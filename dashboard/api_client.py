"""Thin HTTP client the dashboard uses to talk to the FastAPI backend."""

from __future__ import annotations

import os
from typing import Any

import requests

BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
V1 = f"{BASE_URL}/api/v1"
TIMEOUT = 15


class ApiError(RuntimeError):
    pass


def _get(path: str, **params: Any) -> Any:
    try:
        resp = requests.get(path, params=params or None, timeout=TIMEOUT)
    except requests.RequestException as exc:  # network / connection error
        raise ApiError(f"無法連線到後端 API ({BASE_URL})：{exc}") from exc
    if resp.status_code >= 400:
        raise ApiError(f"{resp.status_code}: {resp.text}")
    return resp.json()


def _post(path: str, json: Any = None) -> Any:
    try:
        resp = requests.post(path, json=json, timeout=TIMEOUT)
    except requests.RequestException as exc:
        raise ApiError(f"無法連線到後端 API ({BASE_URL})：{exc}") from exc
    if resp.status_code >= 400:
        raise ApiError(f"{resp.status_code}: {resp.text}")
    return resp.json()


def health() -> dict:
    return _get(f"{BASE_URL}/health")


def wind_farms() -> list[dict]:
    return _get(f"{V1}/wind-farms", limit=1000)


def customers() -> list[dict]:
    return _get(f"{V1}/customers", limit=1000)


def contracts() -> list[dict]:
    return _get(f"{V1}/contracts", limit=1000)


def generation(wind_farm_id: int | None = None) -> list[dict]:
    params = {"wind_farm_id": wind_farm_id} if wind_farm_id else {}
    return _get(f"{V1}/generation", limit=5000, **params)


def consumption(customer_id: int | None = None) -> list[dict]:
    params = {"customer_id": customer_id} if customer_id else {}
    return _get(f"{V1}/consumption", limit=5000, **params)


def run_matching(period: str) -> dict:
    return _post(f"{V1}/matching/runs", json={"period": period})


def matching_results(run_id: int) -> list[dict]:
    return _get(f"{V1}/matching/results", run_id=run_id, limit=5000)


def analytics_customers(period: str) -> list[dict]:
    return _get(f"{V1}/analytics/customers", period=period)


def analytics_wind_farms(period: str) -> list[dict]:
    return _get(f"{V1}/analytics/wind-farms", period=period)


def analytics_summary(period: str) -> dict:
    return _get(f"{V1}/analytics/summary", period=period)


def live_renewables(force: bool = False) -> dict:
    params = {"force": "true"} if force else {}
    return _get(f"{V1}/live/renewables", **params)
