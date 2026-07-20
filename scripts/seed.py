"""Seed the database with a chosen dataset (one-click).

Usage:
    python -m scripts.seed                         # bundled demo (data/sample)
    python -m scripts.seed --reset                 # drop & recreate tables first
    python -m scripts.seed --source taipower       # real Taipower wind open data
    python -m scripts.seed --source taipower --months 12 --fetch

The ``sample`` source loads the bundled demo CSVs and automatically expands the
monthly generation/consumption into peak / half-peak / off-peak time slots, so
the time-based matching, settlement and analytics work out of the box — no
separate step needed. The ``taipower`` source reads Taiwan Power Company's
monthly wind-turbine open data (dataset 29961) for a rolling window of the most
recent N months (default 12): by default from a local file
(``data/taipower/wind_turbines.csv``), or with ``--fetch`` it downloads the CSV
live. Taipower is real monthly data and is left as-is (no synthetic slots).
Taipower supplies only the supply side, so customers / contracts / consumption
stay empty for that source.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from app.db.base import Base
from app.db.session import SessionLocal, create_all, engine
from app.ingestion import csv_importer
from app.ingestion.sources import CsvDataSource
from app.ingestion.taipower import DEFAULT_MONTHS, TaipowerWindSource
from app.services.trec_service import get_ledger, issue_for_period, retire
from scripts.generate_meter_profiles import split_consumption_to_meters
from scripts.generate_slot_profiles import split_profiles

SAMPLE_DIR = Path(__file__).resolve().parent.parent / "data" / "sample"


def build_source(
    name: str,
    months: int = DEFAULT_MONTHS,
    fetch: bool = False,
    csv_path: str | None = None,
):
    """Return a ``DataSource`` for the given source name."""
    if name == "taipower":
        return TaipowerWindSource(months=months, fetch=fetch, csv_path=csv_path)
    if name == "sample":
        return CsvDataSource(SAMPLE_DIR)
    raise ValueError(f"unknown source: {name!r} (expected 'sample' or 'taipower')")


def seed(source, reset: bool = False, slot_profiles: bool = True) -> None:
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
            ("meters", csv_importer.import_meters, source.meters()),
        ]
        for label, importer, rows in steps:
            result = importer(db, rows)
            print(
                f"{label:<12}: imported={result.imported} "
                f"skipped={result.skipped} errors={len(result.errors)}"
            )
            for err in result.errors[:5]:
                print(f"    ! {err}")
        if slot_profiles:
            split_profiles(db)
            print("時段展開      : 發電/用電已拆為尖峰・半尖峰・離峰時段")
            split_consumption_to_meters(db)
            print("電號拆分      : 用電已歸屬至各電號/廠區")
            issue_for_period(db, "2024-01")
            for row in get_ledger(db, period="2024-01").batches[:2]:
                retire(db, row.id)  # retire a couple to show both statuses
            print("T-REC 憑證    : 已由 2024-01 媒合結果發行")
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
        "--months",
        type=int,
        default=DEFAULT_MONTHS,
        help="taipower: import the most recent N months of data (default: 12)",
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
        args.source, months=args.months, fetch=args.fetch, csv_path=args.csv_path
    )
    # Synthetic time slots only for the demo sample; real Taipower data is left as-is.
    seed(source, reset=args.reset, slot_profiles=(args.source == "sample"))


if __name__ == "__main__":
    main()
