# tests/unit/test_evaluation.py
from __future__ import annotations

import pytest

from app.core.exceptions import NotFoundError
from app.ingestion import csv_importer
from app.services import evaluation


def _seed(db):
    # 1 farm (feed-in 4.0), 1 customer (1000 MWh/yr split monthly by seed), 1 contract
    # priced 5.0, 100% of farm. Generation 100 MWh in 2025-01; consumption 200 MWh.
    csv_importer.import_wind_farms(
        db,
        [
            {
                "code": "WF-A",
                "name": "A",
                "installed_capacity_mw": "10",
                "status": "operational",
                "feed_in_price_per_kwh": "4.0",
            }
        ],
    )
    csv_importer.import_customers(
        db,
        [
            {
                "code": "CU-A",
                "company_name": "Alpha",
                "annual_consumption_mwh": "2400",
                "re_target_percent": "50",
            }
        ],
    )
    csv_importer.import_contracts(
        db,
        [
            {
                "contract_number": "PPA-A",
                "wind_farm_code": "WF-A",
                "customer_code": "CU-A",
                "start_date": "2025-01-01",
                "end_date": "2030-12-31",
                "contracted_percentage": "100",
                "price_per_kwh": "5.0",
                "priority": "1",
                "status": "active",
            }
        ],
    )
    csv_importer.import_generation(
        db,
        [
            {
                "wind_farm_code": "WF-A",
                "period_start": "2025-01-01",
                "period_end": "2025-01-31",
                "generated_energy_mwh": "100",
                "data_source": "test",
            }
        ],
    )
    csv_importer.import_consumption(
        db,
        [
            {
                "customer_code": "CU-A",
                "period_start": "2025-01-01",
                "period_end": "2025-01-31",
                "consumed_energy_mwh": "200",
                "data_source": "test",
            }
        ],
    )


def test_evaluate_seller_and_buyer_economics(db):
    _seed(db)
    r = evaluation.evaluate(
        db, _customer_id(db, "CU-A"), start="2025-01", end="2025-01"
    )

    # Allocation is min(farm 100, customer 200, cap 100%) = 100 MWh = 100_000 kWh.
    assert r.buyer.green_mwh == pytest.approx(100.0)
    assert r.buyer.grey_mwh == pytest.approx(100.0)  # 200 consumed − 100 green
    # Seller: cost 100_000×4.0 = 400_000 ; revenue 100_000×5.0 = 500_000.
    assert r.seller.procurement_cost == pytest.approx(400_000.0)
    assert r.seller.sales_revenue == pytest.approx(500_000.0)
    assert r.seller.gross_profit == pytest.approx(100_000.0)
    assert r.seller.gross_margin_percent == pytest.approx(20.0)
    # Buyer: RE% = 100/200 = 50 ; added cost = 100_000×(5.0−3.0) = 200_000.
    assert r.buyer.re_percent == pytest.approx(50.0)
    assert r.buyer.added_cost == pytest.approx(200_000.0)
    # avg = (green 100_000×5.0 + grey 100_000×3.0)/200_000 = 4.0
    assert r.buyer.avg_price_per_kwh == pytest.approx(4.0)
    assert r.used_default_feed_in_price is False


def test_evaluate_unknown_customer_raises(db):
    with pytest.raises(NotFoundError):
        evaluation.evaluate(db, 999999)


def _customer_id(db, code):
    from app.models import Customer

    return db.query(Customer).filter_by(code=code).one().id
