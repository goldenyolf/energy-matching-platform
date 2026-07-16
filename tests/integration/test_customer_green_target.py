from __future__ import annotations

from app.ingestion import csv_importer
from app.models import Customer
from app.models.enums import GreenTargetType


def test_import_customer_defaults_to_re_percent(db):
    csv_importer.import_customers(
        db,
        [
            {
                "code": "CUST-A",
                "company_name": "A",
                "annual_consumption_mwh": "1000",
                "re_target_percent": "60",
            }
        ],
    )
    c = db.query(Customer).filter_by(code="CUST-A").one()
    assert c.green_target_type == GreenTargetType.RE_PERCENT
    assert c.target_energy_mwh is None


def test_import_customer_energy_target(db):
    csv_importer.import_customers(
        db,
        [
            {
                "code": "CUST-B",
                "company_name": "B",
                "annual_consumption_mwh": "1000",
                "green_target_type": "energy",
                "target_energy_mwh": "300",
            }
        ],
    )
    c = db.query(Customer).filter_by(code="CUST-B").one()
    assert c.green_target_type == GreenTargetType.ENERGY
    assert c.target_energy_mwh == 300.0
