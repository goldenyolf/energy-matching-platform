"""Battery (客戶側儲能) ORM model (A8)."""

from __future__ import annotations

import pytest

from app.models import Battery, Customer


@pytest.fixture()
def customer(db):
    c = Customer(code="K1", company_name="用電廠一", industry="電源管理")
    db.add(c)
    db.commit()
    return c


def test_battery_round_trips_with_its_customer(db, customer):
    db.add(
        Battery(
            code="BAT-1",
            customer_id=customer.id,
            name="示範儲能",
            energy_capacity_mwh=120.0,
            power_mw=30.0,
        )
    )
    db.commit()

    row = db.query(Battery).one()
    assert row.customer_id == customer.id
    assert row.energy_capacity_mwh == 120.0
    assert row.power_mw == 30.0


def test_efficiency_and_soc_have_sensible_defaults(db, customer):
    db.add(
        Battery(
            code="BAT-1",
            customer_id=customer.id,
            name="示範儲能",
            energy_capacity_mwh=10.0,
            power_mw=5.0,
        )
    )
    db.commit()

    row = db.query(Battery).one()
    assert row.round_trip_efficiency_percent == 88.0  # 往返效率預設
    assert row.initial_soc_percent == 0.0  # 期初空的


def test_deleting_a_customer_removes_its_batteries(db, customer):
    """電池是客戶的子表 → 刪客戶要一起帶走,不能留下指向死 id 的孤兒。"""
    db.add(
        Battery(
            code="BAT-1",
            customer_id=customer.id,
            name="示範儲能",
            energy_capacity_mwh=120.0,
            power_mw=30.0,
        )
    )
    db.commit()

    db.delete(customer)
    db.commit()

    assert db.query(Battery).count() == 0
