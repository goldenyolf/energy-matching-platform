from __future__ import annotations

from datetime import date

from app.models import ConsumptionData, Customer, Meter


def test_meter_belongs_to_customer(db):
    c = Customer(code="C1", company_name="X")
    db.add(c)
    db.flush()
    m = Meter(code="M1", customer_id=c.id, name="台南廠", re_target_percent=90.0)
    db.add(m)
    db.flush()
    db.add(
        ConsumptionData(
            customer_id=c.id,
            meter_id=m.id,
            period_start=date(2024, 1, 1),
            period_end=date(2024, 1, 31),
            consumed_energy_mwh=100.0,
        )
    )
    db.commit()
    assert db.query(Meter).one().name == "台南廠"
    assert db.query(ConsumptionData).one().meter_id == m.id
    assert c.meters[0].code == "M1"
