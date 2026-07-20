from __future__ import annotations

from datetime import date

import pytest

from app.core.exceptions import NotFoundError
from app.models import ConsumptionData, Contract, Customer, GenerationData, WindFarm
from app.models.enums import ContractStatus
from app.services.trec_service import get_ledger, issue_for_period, retire


def _seed(db):
    f = WindFarm(
        code="WF", name="F", installed_capacity_mw=100, feed_in_price_per_kwh=4.0
    )
    c = Customer(code="CU", company_name="X", re_target_percent=50.0)
    db.add_all([f, c])
    db.flush()
    db.add(
        GenerationData(
            wind_farm_id=f.id,
            period_start=date(2024, 1, 1),
            period_end=date(2024, 1, 31),
            generated_energy_mwh=300.0,
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
    db.add(
        Contract(
            contract_number="C1",
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
    return f, c


def test_issue_idempotent_and_retire(db):
    _seed(db)
    n = issue_for_period(db, "2024-01")
    assert n >= 1
    assert issue_for_period(db, "2024-01") == 0  # idempotent
    led = get_ledger(db, period="2024-01")
    assert led.summary.total_batches == n
    assert led.summary.transferred_mwh > 0
    assert led.summary.retired_mwh == 0

    batch_id = led.batches[0].id
    retire(db, batch_id)
    led2 = get_ledger(db, period="2024-01")
    assert led2.summary.retired_batches == 1
    assert led2.summary.transferred_mwh + led2.summary.retired_mwh == pytest.approx(
        led2.summary.total_quantity_mwh
    )


def test_retire_unknown_raises(db):
    with pytest.raises(NotFoundError):
        retire(db, 999999)
