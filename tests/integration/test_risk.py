from __future__ import annotations

from datetime import date

from app.models import ConsumptionData, Contract, Customer, GenerationData, WindFarm
from app.models.enums import ContractStatus
from app.services.risk_service import compute_contract_risks

REF = date(2026, 7, 20)


def _farm(db, code="WF-A", cap=100.0):
    f = WindFarm(
        code=code, name=code, installed_capacity_mw=cap, feed_in_price_per_kwh=4.0
    )
    db.add(f)
    db.flush()
    return f


def _cust(db, code="CU-A", target=50.0):
    c = Customer(code=code, company_name=code, re_target_percent=target)
    db.add(c)
    db.flush()
    return c


def _contract(
    db,
    f,
    c,
    num,
    *,
    pct=None,
    energy=None,
    prio=1,
    status=ContractStatus.ACTIVE,
    start=date(2025, 1, 1),
    end=date(2032, 12, 31),
):
    ct = Contract(
        contract_number=num,
        wind_farm_id=f.id,
        customer_id=c.id,
        start_date=start,
        end_date=end,
        contracted_percentage=pct,
        contracted_energy_mwh=energy,
        price_per_kwh=5.0,
        priority=prio,
        status=status,
    )
    db.add(ct)
    db.commit()
    return ct


def test_expiry_medium(db):
    f, c = _farm(db), _cust(db)
    _contract(db, f, c, "X1", pct=50, end=date(2026, 9, 15))
    rep = compute_contract_risks(db, "2024-01", reference_date=REF, horizon_months=6)
    ex = [a for a in rep.alerts if a.category == "expiry"]
    assert ex and ex[0].severity == "medium" and ex[0].contract_number == "X1"


def test_status_mismatch_not_expiry(db):
    f, c = _farm(db), _cust(db)
    _contract(db, f, c, "X2", pct=50, end=date(2026, 3, 1))  # past, still active
    rep = compute_contract_risks(db, "2024-01", reference_date=REF, horizon_months=6)
    cats = {a.category for a in rep.alerts}
    assert "status_mismatch" in cats and "expiry" not in cats


def test_over_commitment_high(db):
    f, c = _farm(db), _cust(db)
    _contract(db, f, c, "X3", pct=70, prio=1)
    _contract(db, f, c, "X4", pct=60, prio=2)
    rep = compute_contract_risks(db, "2024-01", reference_date=REF, horizon_months=6)
    oc = [a for a in rep.alerts if a.category == "over_commitment"]
    assert oc and oc[0].severity == "high" and oc[0].wind_farm_code == "WF-A"


def test_under_delivery(db):
    f, c = _farm(db), _cust(db)
    db.add(
        GenerationData(
            wind_farm_id=f.id,
            period_start=date(2024, 1, 1),
            period_end=date(2024, 1, 31),
            generated_energy_mwh=100.0,
        )
    )
    db.add(
        ConsumptionData(
            customer_id=c.id,
            period_start=date(2024, 1, 1),
            period_end=date(2024, 1, 31),
            consumed_energy_mwh=500.0,
        )
    )
    _contract(db, f, c, "X5", pct=80, prio=1)
    _contract(db, f, c, "X6", pct=80, prio=2)
    rep = compute_contract_risks(db, "2024-01", reference_date=REF, horizon_months=6)
    ud = [a for a in rep.alerts if a.category == "under_delivery"]
    assert any(a.contract_number == "X6" for a in ud)


def test_no_risk_counts_consistent(db):
    f, c = _farm(db), _cust(db)
    _contract(db, f, c, "OK", pct=50, end=date(2032, 12, 31))
    rep = compute_contract_risks(db, "2099-01", reference_date=REF, horizon_months=6)
    assert rep.counts.total == len(rep.alerts)
