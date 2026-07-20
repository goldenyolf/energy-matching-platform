from __future__ import annotations

from datetime import date

import pytest

from app.models import ConsumptionData, Customer, Meter
from app.models.enums import TimeSlot
from scripts.generate_meter_profiles import split_consumption_to_meters


def test_split_consumption_to_meters(db):
    c = Customer(code="C1", company_name="X")
    db.add(c)
    db.flush()
    m1 = Meter(
        code="M1",
        customer_id=c.id,
        name="A",
        re_target_percent=80.0,
        annual_consumption_mwh=60.0,
    )
    m2 = Meter(
        code="M2",
        customer_id=c.id,
        name="B",
        re_target_percent=40.0,
        annual_consumption_mwh=40.0,
    )
    db.add_all([m1, m2])
    db.flush()
    db.add(
        ConsumptionData(
            customer_id=c.id,
            meter_id=None,
            period_start=date(2024, 1, 1),
            period_end=date(2024, 1, 31),
            consumed_energy_mwh=100.0,
            time_slot=TimeSlot.PEAK,
        )
    )
    db.commit()

    split_consumption_to_meters(db)
    rows = db.query(ConsumptionData).all()
    assert all(r.meter_id is not None for r in rows)
    assert all(r.time_slot == TimeSlot.PEAK for r in rows)  # slot preserved
    assert sum(r.consumed_energy_mwh for r in rows) == pytest.approx(100.0)
    by_meter = {r.meter_id: r.consumed_energy_mwh for r in rows}
    assert by_meter[m1.id] == pytest.approx(60.0)  # 60/40 share
    assert by_meter[m2.id] == pytest.approx(40.0)

    # idempotent: rows already tagged are left alone
    split_consumption_to_meters(db)
    assert db.query(ConsumptionData).count() == 2


def test_split_no_meters_is_noop(db):
    c = Customer(code="C2", company_name="Y")
    db.add(c)
    db.flush()
    db.add(
        ConsumptionData(
            customer_id=c.id,
            period_start=date(2024, 1, 1),
            period_end=date(2024, 1, 31),
            consumed_energy_mwh=50.0,
        )
    )
    db.commit()
    split_consumption_to_meters(db)
    assert db.query(ConsumptionData).one().meter_id is None
