"""The taipower demand loader creates monthly consumption for each customer over
the Taipower generation window, so matching can allocate TPC- generation. It is
idempotent per (customer, period) and derives the window from the data in the DB
(not a fixed date range), so it stays aligned as the rolling window moves.
"""

from __future__ import annotations

from app.ingestion import csv_importer
from app.models import ConsumptionData
from scripts.seed_taipower_demand import seed_demand


def _seed_farms_and_customers(db):
    csv_importer.import_wind_farms(
        db,
        [
            {
                "code": "TPC-X",
                "name": "X",
                "installed_capacity_mw": "10",
                "status": "operational",
            }
        ],
    )
    csv_importer.import_generation(
        db,
        [
            {
                "wind_farm_code": "TPC-X",
                "period_start": "2026-01-01",
                "period_end": "2026-01-31",
                "generated_energy_mwh": "100",
                "data_source": "taipower",
            },
            {
                "wind_farm_code": "TPC-X",
                "period_start": "2025-12-01",
                "period_end": "2025-12-31",
                "generated_energy_mwh": "100",
                "data_source": "taipower",
            },
        ],
    )
    csv_importer.import_customers(
        db,
        [
            {
                "code": "CUST-A",
                "company_name": "A",
                "industry": "x",
                "annual_consumption_mwh": "1200",
                "re_target_percent": "50",
                "target_year": "2030",
            },
            {
                "code": "CUST-B",
                "company_name": "B",
                "industry": "x",
                "annual_consumption_mwh": "2400",
                "re_target_percent": "50",
                "target_year": "2030",
            },
        ],
    )


def test_creates_consumption_per_customer_per_period(db):
    _seed_farms_and_customers(db)

    created = seed_demand(db)

    assert created == 4  # 2 customers × 2 taipower periods
    rows = db.query(ConsumptionData).all()
    assert len(rows) == 4
    # monthly = annual / 12  → CUST-A: 1200/12 = 100, CUST-B: 2400/12 = 200
    a_rows = [r for r in rows if r.consumed_energy_mwh == 100.0]
    b_rows = [r for r in rows if r.consumed_energy_mwh == 200.0]
    assert len(a_rows) == 2 and len(b_rows) == 2
    assert all(r.period_start.isoformat() in {"2025-12-01", "2026-01-01"} for r in rows)


def test_only_covers_taipower_periods(db):
    _seed_farms_and_customers(db)
    # A pre-existing 2024 demo consumption row must be left untouched and not
    # counted as a taipower-window period.
    csv_importer.import_consumption(
        db,
        [
            {
                "customer_code": "CUST-A",
                "period_start": "2024-01-01",
                "period_end": "2024-01-31",
                "consumed_energy_mwh": "999",
                "data_source": "mock",
            }
        ],
    )

    created = seed_demand(db)

    # Only the 2 taipower periods × 2 customers → the 2024 demo row is untouched.
    assert created == 4
    window_rows = [
        r for r in db.query(ConsumptionData).all() if r.data_source == "taipower-window"
    ]
    assert all(r.period_start.year in {2025, 2026} for r in window_rows)
    assert db.query(ConsumptionData).filter_by(data_source="mock").count() == 1


def test_seed_demand_is_idempotent(db):
    _seed_farms_and_customers(db)
    seed_demand(db)

    again = seed_demand(db)

    assert again == 0
    assert db.query(ConsumptionData).count() == 4
