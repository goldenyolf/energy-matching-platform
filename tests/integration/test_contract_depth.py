"""合約深化: take-or-pay settlement charge + CPI price escalation (end-to-end)."""

from __future__ import annotations

from datetime import date

import pytest

from app.models import ConsumptionData, Contract, Customer, GenerationData, WindFarm
from app.models.enums import ContractStatus, TimeSlot
from app.services.settlement_service import SettlementOptions, compute_settlement


def _seed(db, *, period_year: int, min_offtake=None, escalation=None, base_year=None):
    f = WindFarm(
        code="WF-D", name="風", installed_capacity_mw=100, feed_in_price_per_kwh=4.0
    )
    cust = Customer(code="CU-D", company_name="電子製造企業 B", re_target_percent=100.0)
    db.add_all([f, cust])
    db.flush()
    # Small generation, large demand → delivered green is supply-limited.
    for slot, g, c in [
        (TimeSlot.PEAK, 3.0, 200.0),
        (TimeSlot.HALF_PEAK, 3.0, 200.0),
        (TimeSlot.OFF_PEAK, 4.0, 200.0),
    ]:
        db.add(
            GenerationData(
                wind_farm_id=f.id,
                period_start=date(period_year, 1, 1),
                period_end=date(period_year, 1, 31),
                generated_energy_mwh=g,
                time_slot=slot,
            )
        )
        db.add(
            ConsumptionData(
                customer_id=cust.id,
                period_start=date(period_year, 1, 1),
                period_end=date(period_year, 1, 31),
                consumed_energy_mwh=c,
                time_slot=slot,
            )
        )
    db.add(
        Contract(
            contract_number="PPA-D",
            wind_farm_id=f.id,
            customer_id=cust.id,
            start_date=date(2020, 1, 1),
            end_date=date(2035, 12, 31),
            status=ContractStatus.ACTIVE,
            priority=1,
            contracted_energy_mwh=1200.0,  # annual → 100 MWh/month flat
            price_per_kwh=5.0,
            min_offtake_percent=min_offtake,
            price_escalation_percent=escalation,
            price_base_year=base_year,
        )
    )
    db.commit()
    return cust


def test_take_or_pay_charges_for_undelivered_floor(db):
    # Floor = 100 MWh/month × 80% = 80 MWh; only ~10 MWh can be delivered.
    cust = _seed(db, period_year=2024, min_offtake=80.0)
    r = compute_settlement(db, cust.id, "2024-01", SettlementOptions())
    assert r.totals.take_or_pay_shortfall_mwh > 0
    assert r.totals.take_or_pay_charge == pytest.approx(
        r.totals.take_or_pay_shortfall_mwh * 1000 * r.transfer_price_per_kwh, rel=1e-3
    )
    # the shortfall charge is added to what the customer pays
    assert r.totals.take_or_pay_charge > 0


def test_no_take_or_pay_without_floor(db):
    cust = _seed(db, period_year=2024, min_offtake=None)
    r = compute_settlement(db, cust.id, "2024-01", SettlementOptions())
    assert r.totals.take_or_pay_shortfall_mwh == 0.0
    assert r.totals.take_or_pay_charge == 0.0


def test_cpi_escalation_raises_transfer_price(db):
    # base price 5.0, 10%/yr from 2024 → 2027 is 5 × 1.1^3 ≈ 6.655
    cust = _seed(db, period_year=2027, escalation=10.0, base_year=2024)
    r = compute_settlement(db, cust.id, "2027-01", SettlementOptions())
    assert r.transfer_price_per_kwh == pytest.approx(5.0 * 1.1**3, rel=1e-3)
