"""Generate the 12-month generation/consumption sample CSVs (deterministic).

Reads the hand-authored wind_farms.csv / customers.csv and expands each entity's
annual figure into 12 monthly rows via the MockDataGenerator seasonal profile.

Usage:
    python -m scripts.generate_sample_data
"""

from __future__ import annotations

import csv
from pathlib import Path

from app.ingestion.csv_importer import parse_csv
from app.ingestion.sources import MockDataGenerator

SAMPLE_DIR = Path(__file__).resolve().parent.parent / "data" / "sample"
YEAR = 2024

# Annual generation per farm (MWh) — expanded to monthly by the wind profile.
FARM_ANNUAL_GENERATION = {
    "WF-FORMOSA2": 1_200_000,
    "WF-CHANGFANG": 2_000_000,
    "WF-ZHONGTUN": 60_000,
}


def _write(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {len(rows):>3} rows -> {path.relative_to(SAMPLE_DIR.parent.parent)}")


def main() -> None:
    gen = MockDataGenerator(year=YEAR)

    generation_rows: list[dict] = []
    for farm in parse_csv((SAMPLE_DIR / "wind_farms.csv").read_text("utf-8")):
        annual = FARM_ANNUAL_GENERATION[farm["code"]]
        generation_rows.extend(gen.generation_rows(farm["code"], annual))
    _write(
        SAMPLE_DIR / "generation.csv",
        [
            "wind_farm_code",
            "period_start",
            "period_end",
            "generated_energy_mwh",
            "data_source",
        ],
        generation_rows,
    )

    consumption_rows: list[dict] = []
    for cust in parse_csv((SAMPLE_DIR / "customers.csv").read_text("utf-8")):
        annual = float(cust["annual_consumption_mwh"])
        consumption_rows.extend(gen.consumption_rows(cust["code"], annual))
    _write(
        SAMPLE_DIR / "consumption.csv",
        [
            "customer_code",
            "period_start",
            "period_end",
            "consumed_energy_mwh",
            "data_source",
        ],
        consumption_rows,
    )


if __name__ == "__main__":
    main()
