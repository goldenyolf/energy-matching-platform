from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select

from app.models import (
    ConsumptionData,
    Contract,
    Customer,
    GenerationData,
    Meter,
    WindFarm,
)
from app.models.enums import ContractStatus, TimeSlot
from app.services.meter_service import compute_meter_breakdown


def _seed_two_meters(db):
    f = WindFarm(
        code="WF-A", name="A", installed_capacity_mw=100, feed_in_price_per_kwh=4.0
    )
    c = Customer(code="CU-A", company_name="Alpha", re_target_percent=60.0)
    db.add_all([f, c])
    db.flush()
    tn = Meter(
        code="TN",
        customer_id=c.id,
        name="台南廠",
        re_target_percent=90.0,
        annual_consumption_mwh=60.0,
    )
    kh = Meter(
        code="KH",
        customer_id=c.id,
        name="高雄廠",
        re_target_percent=40.0,
        annual_consumption_mwh=40.0,
    )
    db.add_all([tn, kh])
    db.flush()
    for slot, g in [(TimeSlot.PEAK, 40.0), (TimeSlot.OFF_PEAK, 60.0)]:
        db.add(
            GenerationData(
                wind_farm_id=f.id,
                period_start=date(2024, 1, 1),
                period_end=date(2024, 1, 31),
                generated_energy_mwh=g,
                time_slot=slot,
            )
        )
    for m, tot in [(tn, 60.0), (kh, 40.0)]:
        for slot, frac in [(TimeSlot.PEAK, 0.5), (TimeSlot.OFF_PEAK, 0.5)]:
            db.add(
                ConsumptionData(
                    customer_id=c.id,
                    meter_id=m.id,
                    period_start=date(2024, 1, 1),
                    period_end=date(2024, 1, 31),
                    consumed_energy_mwh=tot * frac,
                    time_slot=slot,
                )
            )
    db.add(
        Contract(
            contract_number="P1",
            wind_farm_id=f.id,
            customer_id=c.id,
            start_date=date(2024, 1, 1),
            end_date=date(2030, 12, 31),
            status=ContractStatus.ACTIVE,
            priority=1,
            contracted_percentage=100.0,
            price_per_kwh=5.0,
        )
    )
    db.commit()
    return c


def test_target_priority_distribution(db):
    c = _seed_two_meters(db)
    r = compute_meter_breakdown(db, c.id, "2024-01")
    assert r.meter_count == 2
    assert r.meters[0].re_target_percent == 90.0  # sorted high-target first
    assert sum(m.allocated_green_mwh for m in r.meters) == pytest.approx(
        r.total_green_mwh, abs=1e-6
    )
    tn = next(m for m in r.meters if m.code == "TN")
    kh = next(m for m in r.meters if m.code == "KH")
    # high-target meter is filled before the low-target one
    assert tn.allocated_green_mwh >= kh.allocated_green_mwh
    # no meter's RE% exceeds 100
    assert all(m.re_percent <= 100.0 + 1e-6 for m in r.meters)


def test_total_kwh_drives_consumption_share_and_tou(db):
    c = _seed_two_meters(db)
    # Stored load data in a 20:80 ratio — different from annual_consumption_mwh
    # (60:40). The breakdown consumption must now follow total_kwh, and the TOU
    # split must appear for the meter that carries slot fields.
    meters = list(db.execute(select(Meter).where(Meter.customer_id == c.id)).scalars())
    for m in meters:
        if m.code == "TN":
            m.total_kwh = 20_000_000.0
            m.peak_kwh, m.half_peak_kwh = 4_000_000.0, 8_000_000.0
            m.saturday_half_peak_kwh, m.off_peak_kwh = 2_000_000.0, 6_000_000.0
        else:
            m.total_kwh = 80_000_000.0  # no slot fields → TOU stays None
    db.commit()

    r = compute_meter_breakdown(db, c.id, "2024-01")
    tn = next(m for m in r.meters if m.code == "TN")
    kh = next(m for m in r.meters if m.code == "KH")
    total = tn.consumption_mwh + kh.consumption_mwh
    assert total > 0
    assert tn.consumption_mwh / total == pytest.approx(
        0.2, rel=1e-3
    )  # follows total_kwh
    # TOU split present, sums back to consumption, Saturday folded into half-peak
    assert tn.peak_mwh is not None
    assert tn.peak_mwh + tn.half_peak_mwh + tn.off_peak_mwh == pytest.approx(
        tn.consumption_mwh, abs=1e-2
    )
    assert tn.half_peak_mwh == pytest.approx(
        tn.consumption_mwh * (8 + 2) / (4 + 8 + 2 + 6), rel=1e-3
    )
    assert kh.peak_mwh is None  # no slot fields → no TOU


def test_no_meters_customer(db):
    c = Customer(code="CU-B", company_name="Beta", re_target_percent=50.0)
    db.add(c)
    db.commit()
    r = compute_meter_breakdown(db, c.id, "2024-01")
    assert r.meter_count == 0 and r.meters == []
