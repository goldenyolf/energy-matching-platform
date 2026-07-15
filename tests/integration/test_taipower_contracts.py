"""The synthetic TPC- demo contracts CSV loads cleanly and binds customers to
Taipower (TPC-) wind farms. These contracts are demo data — Taipower publishes
no contract data — so they live with the sample dataset, not the real adapter.
"""

from __future__ import annotations

from collections import defaultdict

from app.ingestion import csv_importer
from app.ingestion.csv_importer import parse_csv
from app.models import Contract, WindFarm
from scripts.seed_taipower_contracts import CONTRACTS_CSV, load


def _seed_referenced_entities(db):
    """Create the wind farms & customers the contracts reference, via importers."""
    rows = parse_csv(CONTRACTS_CSV.read_text(encoding="utf-8"))
    wf_codes = sorted({r["wind_farm_code"] for r in rows})
    cust_codes = sorted({r["customer_code"] for r in rows})
    csv_importer.import_wind_farms(
        db,
        [
            {
                "code": c,
                "name": c,
                "installed_capacity_mw": "10",
                "status": "operational",
            }
            for c in wf_codes
        ],
    )
    csv_importer.import_customers(
        db,
        [
            {
                "code": c,
                "company_name": c,
                "industry": "demo",
                "annual_consumption_mwh": "100000",
                "re_target_percent": "50",
                "target_year": "2030",
            }
            for c in cust_codes
        ],
    )
    return rows


def test_loader_imports_all_contracts(db):
    _seed_referenced_entities(db)

    result = load(db)

    assert result.errors == []
    assert result.imported == 8
    assert result.skipped == 0


def test_all_contracts_bind_to_tpc_farms(db):
    _seed_referenced_entities(db)
    load(db)

    contracts = db.query(Contract).all()
    assert len(contracts) == 8
    codes = {db.get(WindFarm, c.wind_farm_id).code for c in contracts}
    assert codes and all(code.startswith("TPC-") for code in codes)


def test_loader_is_idempotent(db):
    _seed_referenced_entities(db)
    load(db)
    second = load(db)

    assert second.imported == 0
    assert second.skipped == 8
    assert db.query(Contract).count() == 8


def test_per_farm_percentage_within_100():
    rows = parse_csv(CONTRACTS_CSV.read_text(encoding="utf-8"))
    pct = defaultdict(float)
    for r in rows:
        if r.get("contracted_percentage"):
            pct[r["wind_farm_code"]] += float(r["contracted_percentage"])
    assert all(total <= 100 for total in pct.values()), dict(pct)
