"""Taipower wind open-data adapter (Phase-2 real data source).

Reads Taiwan Power Company's public "wind turbine generation & hours" dataset
(data.gov.tw dataset 29961) and exposes it through the same ``DataSource``
protocol as the CSV / mock sources, so it drops straight into ``csv_importer``
and ``scripts.seed`` with no other changes.

Source CSV (UTF-8, monthly, one row per turbine per month)::

    年度/Year, 月份/Month, 縣市/County, 縣市別代碼, 發電站名稱/Station Name,
    風機編號/Wind Turbine Number, 裝置容量(kW), 風機發電量(度)/kWh,
    風機發電時數(小時), 風機未發電時數(小時)

The adapter aggregates the per-turbine rows to the station level that the rest
of the platform models: one wind farm per station, one monthly generation total
per station. Missing cells (``-``) are skipped. Only Taipower's own (mostly
onshore) stations appear here — offshore IPP farms are not in this dataset.

Access note: data.gov.tw is an official open-data platform under the Government
Open Data Licence v1. Any fetch honours that licence; this adapter does not
scrape restricted endpoints or bypass access controls.
"""

from __future__ import annotations

import calendar
import re
from datetime import date
from pathlib import Path

from app.ingestion import parsing as p
from app.ingestion.csv_importer import parse_csv
from app.models.enums import WindFarmStatus

DEFAULT_URL = (
    "https://service.taipower.com.tw/data/opendata/apply/file/d693004/001.csv"
)
DEFAULT_CSV_PATH = Path("data/taipower/wind_turbines.csv")
DEFAULT_YEAR = 2024
OPERATOR_NAME = "台灣電力公司"

# Logical field -> a stable substring that identifies its (bilingual) header.
# Chinese tokens are used because they are unambiguous and punctuation-stable;
# "縣市/" is deliberately specific so it does not match "縣市別代碼" (county code).
_COLUMN_TOKENS = {
    "year": "年度",
    "month": "月份",
    "county": "縣市/",
    "station": "發電站名稱",
    "turbine": "風機編號",
    "capacity": "裝置容量",
    "generation": "風機發電量",
}

_STATION_SUFFIX = re.compile(r"wind power station$", re.IGNORECASE)
_NON_SLUG = re.compile(r"[^0-9A-Za-z]+")


def _http_get(url: str) -> bytes:
    """Download ``url`` and return its bytes (httpx is an optional extra)."""
    try:
        import httpx
    except ModuleNotFoundError as exc:  # pragma: no cover - env-dependent
        raise ModuleNotFoundError(
            "使用 fetch 需要 httpx。請安裝:pip install '.[ingestion]'"
        ) from exc
    resp = httpx.get(url, timeout=30.0, follow_redirects=True)
    resp.raise_for_status()
    return resp.content


def _num(value: str | None) -> float | None:
    """Parse a numeric cell, treating '' and '-' (missing) as ``None``."""
    v = p.s(value)
    if v is None or v == "-":
        return None
    try:
        return float(v)
    except ValueError:
        return None


def _station_slug(station: str) -> str:
    """Derive a stable ASCII code fragment from the English station name.

    ``石門風電站/Shimen Wind Power Station`` -> ``SHIMEN``.
    """
    english = station.split("/")[-1].strip()
    trimmed = _STATION_SUFFIX.sub("", english).strip() or english
    slug = _NON_SLUG.sub("-", trimmed).strip("-").upper()
    return slug or "UNKNOWN"


class TaipowerWindSource:
    """A ``DataSource`` backed by Taipower's monthly wind-turbine open data."""

    def __init__(
        self,
        year: int = DEFAULT_YEAR,
        csv_path: str | Path | None = None,
        fetch: bool = False,
        url: str = DEFAULT_URL,
    ) -> None:
        self._year = int(year)
        self._csv_path = Path(csv_path) if csv_path else DEFAULT_CSV_PATH
        self._fetch = fetch
        self._url = url
        self._rows_cache: list[dict] | None = None
        self._cols_cache: dict[str, str] | None = None

    # -- loading -----------------------------------------------------------

    def _load_content(self) -> bytes:
        if self._fetch:
            return _http_get(self._url)
        if not self._csv_path.exists():
            raise FileNotFoundError(
                f"找不到台電 CSV:{self._csv_path}。請先下載 ({self._url}) "
                f"放到該路徑,或改用 --fetch 即時下載。"
            )
        return self._csv_path.read_bytes()

    def _rows(self) -> list[dict]:
        if self._rows_cache is None:
            self._rows_cache = parse_csv(self._load_content())
        return self._rows_cache

    def _cols(self, rows: list[dict]) -> dict[str, str]:
        if self._cols_cache is None:
            fieldnames = list(rows[0].keys()) if rows else []
            resolved = {}
            for logical, token in _COLUMN_TOKENS.items():
                match = next((f for f in fieldnames if token in f), None)
                if match is None:
                    raise ValueError(
                        f"台電 CSV 缺少欄位:{logical}(預期標題包含 '{token}')"
                    )
                resolved[logical] = match
            self._cols_cache = resolved
        return self._cols_cache

    def _year_rows(self):
        """Yield (row, cols) for rows in the configured year."""
        rows = self._rows()
        cols = self._cols(rows)
        for r in rows:
            if p.i(r.get(cols["year"])) == self._year:
                yield r, cols

    # -- DataSource protocol ----------------------------------------------

    def wind_farms(self) -> list[dict]:
        # code -> (station name, county); code -> {turbine: kW}
        meta: dict[str, tuple[str, str | None]] = {}
        caps: dict[str, dict[str, float]] = {}
        for r, cols in self._year_rows():
            station = p.s(r.get(cols["station"]))
            if not station:
                continue
            code = "TPC-" + _station_slug(station)
            meta.setdefault(code, (station, p.s(r.get(cols["county"]))))
            cap = _num(r.get(cols["capacity"]))
            if cap is not None:
                turbine = p.s(r.get(cols["turbine"])) or ""
                caps.setdefault(code, {})[turbine] = cap

        out = []
        for code, (station, county) in meta.items():
            total_kw = sum(caps.get(code, {}).values())
            out.append(
                {
                    "code": code,
                    "name": station,
                    "operator_name": OPERATOR_NAME,
                    "location": county,
                    "installed_capacity_mw": str(round(total_kw / 1000.0, 3)),
                    "status": WindFarmStatus.OPERATIONAL.value,
                }
            )
        return out

    def generation(self) -> list[dict]:
        totals: dict[tuple[str, int], float] = {}
        for r, cols in self._year_rows():
            station = p.s(r.get(cols["station"]))
            month = p.i(r.get(cols["month"]))
            kwh = _num(r.get(cols["generation"]))
            if not station or month is None or kwh is None:
                continue
            code = "TPC-" + _station_slug(station)
            totals[(code, month)] = totals.get((code, month), 0.0) + kwh

        out = []
        for (code, month), kwh in totals.items():
            last = calendar.monthrange(self._year, month)[1]
            out.append(
                {
                    "wind_farm_code": code,
                    "period_start": date(self._year, month, 1).isoformat(),
                    "period_end": date(self._year, month, last).isoformat(),
                    "generated_energy_mwh": str(round(kwh / 1000.0, 2)),
                    "data_source": "taipower",
                }
            )
        return out

    def customers(self) -> list[dict]:
        return []  # Taipower publishes no demand-side data.

    def contracts(self) -> list[dict]:
        return []

    def consumption(self) -> list[dict]:
        return []
