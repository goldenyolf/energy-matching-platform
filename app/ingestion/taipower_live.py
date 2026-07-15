"""Taipower real-time per-unit generation client (dataset 8931).

Fetches the "instantaneous net generation per unit" JSON (updated every ~10
minutes) and projects it into a wind + renewables live view. This is a snapshot
of **instantaneous MW**, not monthly energy — it is intentionally never persisted
and never feeds the matching engine (which works on monthly MWh).

JSON shape::

    {"DateTime": "2026-07-16T00:10:00",
     "aaData": [{"機組類型": "風力", "機組名稱": "彰工",
                 "裝置容量(MW)": "86.2", "淨發電量(MW)": "5.7", ...}, ...]}

Values carry noise (``-``, blanks, trailing ``(6.238%)``); ``_num`` is forgiving.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable

from app.ingestion._http import http_get
from app.schemas.live import LiveRenewables, LiveUnit, RenewableTypeSummary

LIVE_URL = "https://service.taipower.com.tw/data/opendata/apply/file/d006001/001.json"
WIND_TYPE = "風力"
RENEWABLE_TYPES = {"風力", "太陽能", "水力", "地熱", "生質能", "其它再生能源"}

_TYPE_KEY = "機組類型"
_NAME_KEY = "機組名稱"
_CAP_KEY = "裝置容量(MW)"
_NET_KEY = "淨發電量(MW)"

_PAREN_TAIL = re.compile(r"\(.*\)\s*$")

# Taipower interleaves aggregate rows (subtotal / total) among the per-unit rows;
# summing them would double-count, so they are dropped.
_AGGREGATE_MARKERS = ("小計", "合計", "總計")


def _is_aggregate(name: str) -> bool:
    return any(marker in name for marker in _AGGREGATE_MARKERS)


def _num(value: object) -> float | None:
    """Parse a numeric cell, tolerating '', '-', 'N/A', and trailing '(...)'.

    ``"3850.0(6.238%)"`` -> ``3850.0``.
    """
    if value is None:
        return None
    s = str(value).strip()
    if s in ("", "-", "N/A"):
        return None
    s = _PAREN_TAIL.sub("", s).strip().rstrip("%")
    try:
        return float(s)
    except ValueError:
        return None


def parse_live(payload: dict) -> LiveRenewables:
    """Project the raw Taipower JSON into the live renewables view."""
    rows = payload.get("aaData") or []

    wind: list[LiveUnit] = []
    summary_net: dict[str, float] = {}
    summary_count: dict[str, int] = {}

    for row in rows:
        unit_type = (row.get(_TYPE_KEY) or "").strip()
        if unit_type not in RENEWABLE_TYPES:
            continue
        name = (row.get(_NAME_KEY) or "").strip()
        if _is_aggregate(name):
            continue
        net = _num(row.get(_NET_KEY))
        summary_count[unit_type] = summary_count.get(unit_type, 0) + 1
        summary_net[unit_type] = summary_net.get(unit_type, 0.0) + (net or 0.0)
        if unit_type == WIND_TYPE:
            wind.append(
                LiveUnit(
                    name=name,
                    capacity_mw=_num(row.get(_CAP_KEY)),
                    net_mw=net,
                )
            )

    wind_total = round(sum(u.net_mw for u in wind if u.net_mw is not None), 3)
    summary = [
        RenewableTypeSummary(
            unit_type=t, unit_count=summary_count[t], net_mw=round(summary_net[t], 3)
        )
        for t in summary_net
    ]
    summary.sort(key=lambda s: s.net_mw, reverse=True)
    renewable_total = round(sum(s.net_mw for s in summary), 3)

    return LiveRenewables(
        snapshot_time=payload.get("DateTime"),
        wind=wind,
        wind_total_mw=wind_total,
        renewable_summary=summary,
        renewable_total_mw=renewable_total,
    )


class LiveClient:
    """Fetches and parses the live JSON, with a short TTL cache.

    ``http_get`` and ``clock`` are injectable so tests need no network or wall
    clock. The default cache TTL keeps us well under the data's ~10-minute cadence
    while staying polite to the upstream service.
    """

    def __init__(
        self,
        url: str = LIVE_URL,
        http_get: Callable[[str], bytes] = http_get,
        ttl_seconds: float = 120.0,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._url = url
        self._http_get = http_get
        self._ttl = ttl_seconds
        self._clock = clock
        self._cache: tuple[float, LiveRenewables] | None = None

    def get(self, force: bool = False) -> LiveRenewables:
        now = self._clock()
        if not force and self._cache is not None and now - self._cache[0] < self._ttl:
            return self._cache[1]
        payload = json.loads(self._http_get(self._url).decode("utf-8-sig"))
        snapshot = parse_live(payload)
        self._cache = (now, snapshot)
        return snapshot
