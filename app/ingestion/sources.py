"""Replaceable data-source interface.

The platform never assumes a specific upstream. A ``DataSource`` yields plain row
dicts (the same shape as the CSV columns); importers turn those into DB rows. This
lets us swap a CSV file, a deterministic mock generator, or — in a future phase — a
real public-data adapter, without touching the rest of the system.
"""

from __future__ import annotations

import calendar
from datetime import date
from pathlib import Path
from typing import Protocol, runtime_checkable

from app.ingestion.csv_importer import parse_csv


@runtime_checkable
class DataSource(Protocol):
    def wind_farms(self) -> list[dict]: ...
    def customers(self) -> list[dict]: ...
    def contracts(self) -> list[dict]: ...
    def generation(self) -> list[dict]: ...
    def consumption(self) -> list[dict]: ...


class CsvDataSource:
    """Reads the five entity CSVs from a directory (default: data/sample)."""

    def __init__(self, directory: str | Path) -> None:
        self.dir = Path(directory)

    def _read(self, name: str) -> list[dict]:
        path = self.dir / name
        if not path.exists():
            return []
        return parse_csv(path.read_text(encoding="utf-8"))

    def wind_farms(self) -> list[dict]:
        return self._read("wind_farms.csv")

    def customers(self) -> list[dict]:
        return self._read("customers.csv")

    def contracts(self) -> list[dict]:
        return self._read("contracts.csv")

    def generation(self) -> list[dict]:
        return self._read("generation.csv")

    def consumption(self) -> list[dict]:
        return self._read("consumption.csv")


def _month_periods(year: int) -> list[tuple[str, date, date]]:
    out = []
    for m in range(1, 13):
        last = calendar.monthrange(year, m)[1]
        out.append((f"{year}-{m:02d}", date(year, m, 1), date(year, m, last)))
    return out


# Deterministic seasonal wind profile for Taiwan (stronger in winter monsoon).
_WIND_PROFILE = [
    1.35,
    1.25,
    1.05,
    0.85,
    0.70,
    0.55,
    0.55,
    0.60,
    0.85,
    1.15,
    1.30,
    1.40,
]


class MockDataGenerator:
    """Generate deterministic monthly generation/consumption (no randomness).

    Given base annual figures, it spreads them across 12 months using a fixed
    seasonal profile, so results are stable and reproducible.
    """

    def __init__(self, year: int = 2024) -> None:
        self.year = year

    def generation_rows(
        self, farm_code: str, annual_generation_mwh: float
    ) -> list[dict]:
        weight_sum = sum(_WIND_PROFILE)
        rows = []
        for (_period, start, end), w in zip(
            _month_periods(self.year), _WIND_PROFILE, strict=True
        ):
            energy = round(annual_generation_mwh * w / weight_sum, 2)
            rows.append(
                {
                    "wind_farm_code": farm_code,
                    "period_start": start.isoformat(),
                    "period_end": end.isoformat(),
                    "generated_energy_mwh": str(energy),
                    "data_source": "mock",
                }
            )
        return rows

    def consumption_rows(
        self, customer_code: str, annual_consumption_mwh: float
    ) -> list[dict]:
        rows = []
        for _period, start, end in _month_periods(self.year):
            energy = round(annual_consumption_mwh / 12.0, 2)
            rows.append(
                {
                    "customer_code": customer_code,
                    "period_start": start.isoformat(),
                    "period_end": end.isoformat(),
                    "consumed_energy_mwh": str(energy),
                    "data_source": "mock",
                }
            )
        return rows


class PublicDataAdapter:
    """Placeholder for a future public open-data adapter (Phase 2).

    Intentionally not implemented. Any real adapter MUST respect the source
    site's Terms of Service, robots.txt, authentication and rate limits — this
    project does not bypass access controls or scrape restricted endpoints.
    """

    def __init__(self, *_args, **_kwargs) -> None:
        raise NotImplementedError(
            "PublicDataAdapter is a Phase-2 placeholder. Implement against a "
            "documented, legal public API and honour its ToS / robots.txt."
        )
