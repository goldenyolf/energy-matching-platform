"""Seed the database with a chosen dataset (one-click).

Usage:
    python -m scripts.seed                         # bundled demo (data/sample)
    python -m scripts.seed --reset                 # drop & recreate tables first
    python -m scripts.seed --source taipower       # real Taipower wind open data
    python -m scripts.seed --source taipower --year 2024 --fetch

The ``sample`` source loads the bundled demo CSVs. The ``taipower`` source reads
Taiwan Power Company's monthly wind-turbine open data (dataset 29961): by default
from a local file (``data/taipower/wind_turbines.csv``), or with ``--fetch`` it
downloads the CSV live. Taipower supplies only the supply side, so customers /
contracts / consumption stay empty for that source.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from app.db.base import Base
from app.db.session import SessionLocal, create_all, engine
from app.ingestion import csv_importer
from app.ingestion.sources import CsvDataSource
from app.ingestion.taipower import DEFAULT_YEAR, TaipowerWindSource

SAMPLE_DIR = Path(__file__).resolve().parent.parent / "data" / "sample"


def build_source(
    name: str,
    year: int = DEFAULT_YEAR,
    fetch: bool = False,
    csv_path: str | None = None,
):
    """Return a ``DataSource`` for the given source name."""
    if name == "taipower":
        return TaipowerWindSource(year=year, fetch=fetch, csv_path=csv_path)
    if name == "sample":
        return CsvDataSource(SAMPLE_DIR)
    raise ValueError(f"unknown source: {name!r} (expected 'sample' or 'taipower')")


def seed(source, reset: bool = False) -> None:
    if reset:
        import app.models  # noqa: F401  (register tables)

        Base.metadata.drop_all(bind=engine)
        print("dropped all tables")
    create_all()

    db = SessionLocal()
    try:
        steps = [
            ("wind farms", csv_importer.import_wind_farms, source.wind_farms()),
            ("customers", csv_importer.import_customers, source.customers()),
            ("contracts", csv_importer.import_contracts, source.contracts()),
            ("generation", csv_importer.import_generation, source.generation()),
            ("consumption", csv_importer.import_consumption, source.consumption()),
        ]
        for label, importer, rows in steps:
            result = importer(db, rows)
            print(
                f"{label:<12}: imported={result.imported} "
                f"skipped={result.skipped} errors={len(result.errors)}"
            )
            for err in result.errors[:5]:
                print(f"    ! {err}")
    finally:
        db.close()
    print("seed complete.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed demo data")
    parser.add_argument("--reset", action="store_true", help="drop tables first")
    parser.add_argument(
        "--source",
        choices=["sample", "taipower"],
        default="sample",
        help="dataset to load (default: sample)",
    )
    parser.add_argument(
        "--year",
        type=int,
        default=DEFAULT_YEAR,
        help="year to import for the taipower source",
    )
    parser.add_argument(
        "--fetch",
        action="store_true",
        help="download the taipower CSV live instead of reading a local file",
    )
    parser.add_argument(
        "--csv-path",
        default=None,
        help="local taipower CSV path (default: data/taipower/wind_turbines.csv)",
    )
    args = parser.parse_args()
    source = build_source(
        args.source, year=args.year, fetch=args.fetch, csv_path=args.csv_path
    )
    seed(source, reset=args.reset)


if __name__ == "__main__":
    main()
