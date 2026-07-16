from __future__ import annotations

from app.ingestion import csv_importer
from app.models import WindFarm


def test_import_wind_farm_with_feed_in_price(db):
    csv_importer.import_wind_farms(
        db,
        [
            {
                "code": "WF-X",
                "name": "X",
                "installed_capacity_mw": "10",
                "status": "operational",
                "feed_in_price_per_kwh": "4.2",
            }
        ],
    )
    farm = db.query(WindFarm).filter_by(code="WF-X").one()
    assert farm.feed_in_price_per_kwh == 4.2


def test_feed_in_price_defaults_to_none(db):
    csv_importer.import_wind_farms(
        db,
        [
            {
                "code": "WF-Y",
                "name": "Y",
                "installed_capacity_mw": "5",
                "status": "operational",
            }
        ],
    )
    farm = db.query(WindFarm).filter_by(code="WF-Y").one()
    assert farm.feed_in_price_per_kwh is None
