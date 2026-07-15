"""Load synthetic demo contracts that bind customers to TPC- (Taipower) farms.

These contracts are demo/synthetic — Taipower publishes no contract data, so the
real ``TaipowerWindSource`` returns none. They let the matching engine allocate
the real Taipower wind generation to the demo customers.

Run AFTER the Taipower wind farms and the demo customers have been seeded::

    python -m scripts.seed --reset --source sample          # demo customers etc.
    python -m scripts.seed --source taipower --fetch         # real TPC- farms
    python -m scripts.seed_taipower_contracts                # these contracts

Idempotent on ``contract_number`` — re-running skips existing rows.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from sqlalchemy.orm import Session

from app.db.session import SessionLocal, create_all
from app.ingestion import csv_importer
from app.ingestion.csv_importer import parse_csv
from app.schemas.common import ImportResult

CONTRACTS_CSV = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "sample"
    / "contracts_taipower.csv"
)


def load(db: Session, csv_path: Path = CONTRACTS_CSV) -> ImportResult:
    """Import the TPC- contracts CSV into ``db`` and return the result."""
    rows = parse_csv(csv_path.read_text(encoding="utf-8"))
    return csv_importer.import_contracts(db, rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed TPC- demo contracts")
    parser.add_argument(
        "--csv-path",
        default=None,
        help=f"contracts CSV (default: {CONTRACTS_CSV})",
    )
    args = parser.parse_args()
    csv_path = Path(args.csv_path) if args.csv_path else CONTRACTS_CSV

    create_all()
    db = SessionLocal()
    try:
        result = load(db, csv_path)
        print(
            f"taipower contracts: imported={result.imported} "
            f"skipped={result.skipped} errors={len(result.errors)}"
        )
        for err in result.errors[:10]:
            print(f"    ! {err}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
