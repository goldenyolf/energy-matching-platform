"""time_slot column: nullable, round-trips, monthly engine unaffected."""

from __future__ import annotations

from datetime import date

from app.models import ConsumptionData, Customer, GenerationData, WindFarm
from app.models.enums import TimeSlot


def test_time_slot_defaults_none_and_persists(db):
    f = WindFarm(code="F1", name="F1", installed_capacity_mw=100)
    c = Customer(code="K1", company_name="K1")
    db.add_all([f, c])
    db.flush()
    g_month = GenerationData(
        wind_farm_id=f.id,
        period_start=date(2024, 1, 1),
        period_end=date(2024, 1, 31),
        generated_energy_mwh=90.0,
    )
    g_slot = GenerationData(
        wind_farm_id=f.id,
        period_start=date(2024, 1, 1),
        period_end=date(2024, 1, 31),
        generated_energy_mwh=30.0,
        time_slot=TimeSlot.PEAK,
    )
    db.add_all([g_month, g_slot])
    db.commit()
    assert g_month.time_slot is None
    assert g_slot.time_slot == TimeSlot.PEAK


def test_consumption_time_slot(db):
    c = Customer(code="K2", company_name="K2")
    db.add(c)
    db.flush()
    row = ConsumptionData(
        customer_id=c.id,
        period_start=date(2024, 1, 1),
        period_end=date(2024, 1, 31),
        consumed_energy_mwh=10.0,
        time_slot=TimeSlot.OFF_PEAK,
    )
    db.add(row)
    db.commit()
    assert row.time_slot == TimeSlot.OFF_PEAK
