from __future__ import annotations

from datetime import date

import pytest

from app.models import ConsumptionData, Contract, Customer, GenerationData, WindFarm
from app.models.enums import ContractStatus
from app.services.recommendation_service import compute_re_recommendations


def _seed_gap(db):
    a = WindFarm(
        code="FA", name="A", installed_capacity_mw=100, feed_in_price_per_kwh=4.0
    )
    cheap = WindFarm(
        code="CHEAP", name="Cheap", installed_capacity_mw=100, feed_in_price_per_kwh=3.0
    )
    exp = WindFarm(
        code="EXP", name="Exp", installed_capacity_mw=100, feed_in_price_per_kwh=5.0
    )
    cust = Customer(code="CU", company_name="X", re_target_percent=50.0)
    db.add_all([a, cheap, exp, cust])
    db.flush()
    for f, g in [(a, 200.0), (cheap, 250.0), (exp, 250.0)]:
        db.add(
            GenerationData(
                wind_farm_id=f.id,
                period_start=date(2024, 1, 1),
                period_end=date(2024, 1, 31),
                generated_energy_mwh=g,
            )
        )
    db.add(
        ConsumptionData(
            customer_id=cust.id,
            period_start=date(2024, 1, 1),
            period_end=date(2024, 1, 31),
            consumed_energy_mwh=1000.0,
        )
    )
    # only farm A is contracted; cheap/exp are all surplus; A's 200 → the customer
    db.add(
        Contract(
            contract_number="C-A",
            wind_farm_id=a.id,
            customer_id=cust.id,
            start_date=date(2024, 1, 1),
            end_date=date(2030, 12, 31),
            status=ContractStatus.ACTIVE,
            priority=1,
            contracted_percentage=100.0,
            price_per_kwh=5.0,
        )
    )
    db.commit()
    return cust


def test_cheapest_first_recommendations(db):
    cust = _seed_gap(db)
    r = compute_re_recommendations(db, cust.id, "2024-01")
    assert r.gap_mwh == pytest.approx(300.0, abs=1.0)
    assert r.recommendations[0].code == "CHEAP"  # cheapest first
    assert r.recommendations[0].feed_in_price_per_kwh == 3.0
    total = sum(x.recommended_mwh for x in r.recommendations)
    assert total == pytest.approx(min(r.gap_mwh, 500.0), abs=1.0)
    assert r.fully_closable is True  # 500 surplus > 300 gap
    assert r.residual_gap_mwh == pytest.approx(0.0, abs=1.0)
    cheap = next(x for x in r.recommendations if x.code == "CHEAP")
    assert cheap.recommended_mwh == pytest.approx(250.0, abs=1.0)
    assert cheap.has_existing_contract is False


def test_met_customer_no_recommendations(db):
    cust = Customer(code="MET", company_name="M", re_target_percent=0.0)
    db.add(cust)
    db.commit()
    r = compute_re_recommendations(db, cust.id, "2024-01")
    assert r.recommendations == [] and r.fully_closable is True
