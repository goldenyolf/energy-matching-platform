"""Seed the database with the bundled demo dataset (one-click).

Usage:
    python -m scripts.seed            # load data/sample into the configured DB
    python -m scripts.seed --reset    # drop & recreate tables first
"""

from __future__ import annotations

import argparse
from pathlib import Path

from app.db.base import Base
from app.db.session import SessionLocal, create_all, engine
from app.ingestion import csv_importer
from app.ingestion.sources import CsvDataSource

SAMPLE_DIR = Path(__file__).resolve().parent.parent / "data" / "sample"


def seed(reset: bool = False) -> None:
    if reset:
        import app.models  # noqa: F401  (register tables)

        Base.metadata.drop_all(bind=engine)
        print("dropped all tables")
    create_all()

    source = CsvDataSource(SAMPLE_DIR)
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
    args = parser.parse_args()
    seed(reset=args.reset)


if __name__ == "__main__":
    main()
