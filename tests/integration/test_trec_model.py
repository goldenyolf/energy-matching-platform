from __future__ import annotations

from app.models import Customer, TrecBatch, WindFarm


def test_trec_batch_persists(db):
    f = WindFarm(code="WF", name="F", installed_capacity_mw=10)
    c = Customer(code="CU", company_name="X")
    db.add_all([f, c])
    db.flush()
    b = TrecBatch(
        batch_no="TREC-2024-01-WF-CU",
        wind_farm_id=f.id,
        customer_id=c.id,
        period="2024-01",
        quantity_mwh=100.0,
        status="transferred",
    )
    db.add(b)
    db.commit()
    got = db.query(TrecBatch).one()
    assert got.status == "transferred"
    assert got.wind_farm.code == "WF"
    assert got.customer.code == "CU"
