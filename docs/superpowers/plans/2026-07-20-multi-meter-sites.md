# 多電號/雙廠區 Implementation Plan

> REQUIRED SUB-SKILL: superpowers:executing-plans.

**Goal:** Meters (電號/廠區) as a demand-side sub-unit of a customer, with per-meter RE attainment via target-priority green distribution. Additive; core matching unchanged.

## Global Constraints

- Full gate: `ruff` · `black` · **`mypy app`** · `pytest` · `node --check`. Migration runs on SQLite (CI) + Postgres.
- `_KWH`-free (energy in MWh throughout). Σ meter green == customer green (fully-metered).
- SSH push, per-task commits. Do NOT touch matching/settlement/optimization logic.

---

### Task 1: Meter model + migration

**Files:** Create `app/models/meter.py`; modify `app/models/__init__.py`, `app/models/customer.py`, `app/models/consumption.py`; create `alembic/versions/<rev>_add_meters.py`; test `tests/integration/test_meter_model.py`.

- [ ] **Step 1: failing test** `tests/integration/test_meter_model.py`:

```python
from datetime import date
from app.models import ConsumptionData, Customer, Meter


def test_meter_belongs_to_customer(db):
    c = Customer(code="C1", company_name="X")
    db.add(c); db.flush()
    m = Meter(code="M1", customer_id=c.id, name="台南廠", re_target_percent=90.0)
    db.add(m); db.flush()
    db.add(ConsumptionData(customer_id=c.id, meter_id=m.id, period_start=date(2024,1,1), period_end=date(2024,1,31), consumed_energy_mwh=100.0))
    db.commit()
    assert db.query(Meter).one().name == "台南廠"
    assert db.query(ConsumptionData).one().meter_id == m.id
    assert c.meters[0].code == "M1"
```

- [ ] **Step 2:** run → FAIL (no Meter).

- [ ] **Step 3:** `app/models/meter.py`:

```python
"""Meter (電號/廠區) — a demand-side sub-unit of a customer."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.models.customer import Customer


class Meter(Base, TimestampMixin):
    __tablename__ = "meters"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    location: Mapped[str | None] = mapped_column(String(200), default=None)
    re_target_percent: Mapped[float] = mapped_column(Float, default=0.0)
    annual_consumption_mwh: Mapped[float | None] = mapped_column(Float, default=None)

    customer: Mapped[Customer] = relationship(back_populates="meters")
```

(Check the actual mixin import path used by `customer.py`; match it.)

- [ ] **Step 4:** `app/models/__init__.py`: export `Meter`. `customer.py`: add
  `meters: Mapped[list["Meter"]] = relationship(back_populates="customer", cascade="all, delete-orphan")`
  (+ TYPE_CHECKING import). `consumption.py`: add
  `meter_id: Mapped[int | None] = mapped_column(ForeignKey("meters.id"), index=True, nullable=True, default=None)`.

- [ ] **Step 5:** run test → PASS (tables auto-created by the `db` fixture).

- [ ] **Step 6:** generate migration: `.venv/bin/alembic revision -m "add meters"` → edit to:

```python
def upgrade() -> None:
    op.create_table(
        "meters",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("location", sa.String(length=200), nullable=True),
        sa.Column("re_target_percent", sa.Float(), nullable=False),
        sa.Column("annual_consumption_mwh", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_meters_code"), "meters", ["code"], unique=True)
    op.create_index(op.f("ix_meters_customer_id"), "meters", ["customer_id"])
    with op.batch_alter_table("consumption_data") as batch:
        batch.add_column(sa.Column("meter_id", sa.Integer(), nullable=True))
        batch.create_index(op.f("ix_consumption_data_meter_id"), ["meter_id"])
        batch.create_foreign_key("fk_consumption_meter", "meters", ["meter_id"], ["id"])


def downgrade() -> None:
    with op.batch_alter_table("consumption_data") as batch:
        batch.drop_constraint("fk_consumption_meter", type_="foreignkey")
        batch.drop_index(op.f("ix_consumption_data_meter_id"))
        batch.drop_column("meter_id")
    op.drop_index(op.f("ix_meters_customer_id"), "meters")
    op.drop_index(op.f("ix_meters_code"), "meters")
    op.drop_table("meters")
```

Set `down_revision = "2440c428ccf6"`. (Match the mixin timestamp columns — if `TimestampMixin` names differ, adjust.)

- [ ] **Step 7:** verify migration on a scratch SQLite DB: `DATABASE_URL=sqlite:///./_m.db .venv/bin/alembic upgrade head && … downgrade -1 && … upgrade head`; then `rm _m.db`. Gate. Commit `feat(meter): Meter model + migration`.

---

### Task 2: Schema + breakdown service (TDD)

**Files:** Create `app/schemas/meter.py`, `app/services/meter_service.py`; test `tests/integration/test_meter.py`.

- [ ] **Step 1: failing tests** — 2 meters (targets 90 / 40), gen+cons+contract so the customer gets partial green; assert high-target meter filled first, `Σ allocated == total_green`, `re_percent`/`target_met` per meter; a no-meters customer → `meter_count == 0`, `meters == []`.

```python
from datetime import date
import pytest
from app.models import ConsumptionData, Contract, Customer, GenerationData, Meter, WindFarm
from app.models.enums import ContractStatus, TimeSlot
from app.services.meter_service import compute_meter_breakdown


def _seed_two_meters(db):
    f = WindFarm(code="WF-A", name="A", installed_capacity_mw=100, feed_in_price_per_kwh=4.0)
    c = Customer(code="CU-A", company_name="Alpha", re_target_percent=60.0)
    db.add_all([f, c]); db.flush()
    tn = Meter(code="TN", customer_id=c.id, name="台南廠", re_target_percent=90.0, annual_consumption_mwh=60.0)
    kh = Meter(code="KH", customer_id=c.id, name="高雄廠", re_target_percent=40.0, annual_consumption_mwh=40.0)
    db.add_all([tn, kh]); db.flush()
    for slot, g in [(TimeSlot.PEAK, 40.0), (TimeSlot.OFF_PEAK, 60.0)]:
        db.add(GenerationData(wind_farm_id=f.id, period_start=date(2024,1,1), period_end=date(2024,1,31), generated_energy_mwh=g, time_slot=slot))
    # meter consumption: TN 60, KH 40 across slots
    for m, tot in [(tn, 60.0), (kh, 40.0)]:
        for slot, frac in [(TimeSlot.PEAK, 0.5), (TimeSlot.OFF_PEAK, 0.5)]:
            db.add(ConsumptionData(customer_id=c.id, meter_id=m.id, period_start=date(2024,1,1), period_end=date(2024,1,31), consumed_energy_mwh=tot*frac, time_slot=slot))
    db.add(Contract(contract_number="P1", wind_farm_id=f.id, customer_id=c.id, start_date=date(2024,1,1), end_date=date(2030,12,31), status=ContractStatus.ACTIVE, priority=1, contracted_percentage=100.0, price_per_kwh=5.0))
    db.commit()
    return c


def test_target_priority_distribution(db):
    c = _seed_two_meters(db)
    r = compute_meter_breakdown(db, c.id, "2024-01")
    assert r.meter_count == 2
    assert r.meters[0].re_target_percent == 90.0  # sorted high-target first
    assert sum(m.allocated_green_mwh for m in r.meters) == pytest.approx(r.total_green_mwh, abs=1e-6)
    tn = next(m for m in r.meters if m.code == "TN")
    kh = next(m for m in r.meters if m.code == "KH")
    # high-target meter is filled toward its target before the low-target one
    assert tn.allocated_green_mwh >= kh.allocated_green_mwh


def test_no_meters_customer(db):
    c = Customer(code="CU-B", company_name="Beta", re_target_percent=50.0)
    db.add(c); db.commit()
    r = compute_meter_breakdown(db, c.id, "2024-01")
    assert r.meter_count == 0 and r.meters == []
```

- [ ] **Step 2:** run → FAIL (import). **Step 3:** `app/schemas/meter.py` (per spec). **Step 4:** `app/services/meter_service.py`:

```python
"""Per-meter RE attainment via target-priority green distribution (analysis layer)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ConsumptionData, Meter
from app.schemas.meter import MeterBreakdown, MeterRow
from app.services.customer_optimization_service import (
    CustomerOptimizeOptions,
    compute_customer_optimization,
)
from app.services.matching_service import period_bounds


def compute_meter_breakdown(db: Session, customer_id: int, period: str) -> MeterBreakdown:
    co = compute_customer_optimization(
        db, customer_id, period, CustomerOptimizeOptions()
    )  # 404s if customer unknown
    total_green = co.buyer.green_mwh

    meters = list(
        db.execute(
            select(Meter).where(Meter.customer_id == customer_id)
        ).scalars()
    )
    if not meters:
        return MeterBreakdown(
            customer_id=co.customer_id, customer_code=co.customer_code,
            company_name=co.company_name, period=co.period, meter_count=0,
            total_consumption_mwh=round(co.buyer.total_consumption_mwh, 3),
            total_green_mwh=round(total_green, 3),
            customer_re_percent=round(co.buyer.re_percent, 4),
            meters_meeting_target=0, meters=[],
        )

    start, end = period_bounds(period)
    cons: dict[int, float] = {}
    for m in meters:
        cons[m.id] = sum(
            row.consumed_energy_mwh
            for row in db.execute(
                select(ConsumptionData).where(
                    ConsumptionData.meter_id == m.id,
                    ConsumptionData.period_start >= start,
                    ConsumptionData.period_start <= end,
                )
            ).scalars()
        )

    give: dict[int, float] = {m.id: 0.0 for m in meters}
    remaining = total_green
    # target pass: higher target first (tie: code asc)
    for m in sorted(meters, key=lambda x: (-x.re_target_percent, x.code)):
        tgt = cons[m.id] * m.re_target_percent / 100.0
        g = min(remaining, tgt)
        give[m.id] = g
        remaining -= g
    # leftover pass: top up toward consumption cap, larger meters first
    if remaining > 1e-9:
        for m in sorted(meters, key=lambda x: -cons[x.id]):
            cap = cons[m.id] - give[m.id]
            g = min(cap, remaining)
            give[m.id] += g
            remaining -= g
            if remaining <= 1e-9:
                break

    rows: list[MeterRow] = []
    met = 0
    for m in sorted(meters, key=lambda x: (-x.re_target_percent, x.code)):
        alloc = give[m.id]
        c = cons[m.id]
        re = (alloc / c * 100.0) if c > 0 else 0.0
        is_met = re + 1e-9 >= m.re_target_percent and m.re_target_percent > 0
        if is_met:
            met += 1
        rows.append(
            MeterRow(
                meter_id=m.id, code=m.code, name=m.name, location=m.location,
                consumption_mwh=round(c, 3), allocated_green_mwh=round(alloc, 3),
                re_percent=round(re, 4), re_target_percent=m.re_target_percent,
                target_met=is_met,
            )
        )

    return MeterBreakdown(
        customer_id=co.customer_id, customer_code=co.customer_code,
        company_name=co.company_name, period=co.period, meter_count=len(meters),
        total_consumption_mwh=round(sum(cons.values()), 3),
        total_green_mwh=round(total_green, 3),
        customer_re_percent=round(co.buyer.re_percent, 4),
        meters_meeting_target=met, meters=rows,
    )
```

- [ ] **Step 5:** run → PASS. Gate. Commit `feat(meter): breakdown service + schema`.

---

### Task 3: Endpoint + API test

**Files:** modify `app/api/v1/analytics.py`; test `tests/integration/test_meter_api.py`.

- [ ] Failing API test (seed as Task 2, hit endpoint) → then add route:

```python
from app.schemas.meter import MeterBreakdown
from app.services import meter_service as meter_svc
```
```python
@router.get("/meter-breakdown", response_model=MeterBreakdown)
def meter_breakdown(
    customer_id: int = Query(..., ge=1),
    period: str = _period,
    db: Session = Depends(get_db),
) -> MeterBreakdown:
    """Per-meter RE attainment (target-priority green distribution)."""
    return meter_svc.compute_meter_breakdown(db, customer_id, period)
```

Assert 200, `Σ meter green == total_green_mwh`, unknown customer 404. Gate. Commit `feat(meter): meter-breakdown endpoint`.

---

### Task 4: Seed (meters.csv + import + split)

**Files:** create `data/sample/meters.csv`, `scripts/generate_meter_profiles.py`; modify `app/ingestion/csv_importer.py` (add `import_meters`), `app/ingestion/sources.py` (CsvDataSource.meters()), `scripts/seed.py`; test `tests/integration/test_meter_profiles.py`.

- [ ] `data/sample/meters.csv`:
```
customer_code,code,name,location,re_target_percent,annual_consumption_mwh
CUST-TSMC,TSMC-TN,台南廠,台南,90,250000
CUST-TSMC,TSMC-KH,高雄廠,高雄,60,166667
CUST-AUO,AUO-LT,龍潭廠,桃園,80,40000
CUST-AUO,AUO-TC,台中廠,台中,60,30000
CUST-AUO,AUO-HL,後里廠,台中,40,13333
```
- [ ] `csv_importer.import_meters(db, rows)` — parse + insert `Meter` (resolve customer_code→id; skip unknown with an error row), mirroring `import_customers`.
- [ ] `CsvDataSource.meters()` reads `meters.csv` (empty list if absent, like other optional sources).
- [ ] `scripts/generate_meter_profiles.py` with `split_consumption_to_meters(db)` (TDD in test_meter_profiles): for each customer having meters, split each `meter_id IS NULL` consumption row into per-meter rows weighted by `annual_consumption_mwh` share (last meter absorbs rounding), preserve period/time_slot, delete original. Idempotent.
- [ ] `scripts/seed.py`: import meters step; after `split_profiles`, call `split_consumption_to_meters` for the sample source; friendly line `電號拆分      : 用電已歸屬至各電號/廠區`.
- [ ] Re-seed local, verify: meters present, meter consumption sums to the customer's total per period. Gate. Commit `chore(meter): demo meters + seed split`.

---

### Task 5: SPA page

**Files:** modify `web/api.js`, `web/index.html`, `web/app.js`.

- [ ] `web/api.js`: `meterBreakdown(customerId, period)`.
- [ ] `web/index.html`: nav under 資料管理 after 企業客戶: `<a data-route="meters">…多電號</a>` (icon: a meter/grid glyph).
- [ ] `web/app.js`: router `meters: renderMeters`; `renderMeters` (customer+period form) → `renderMeterBreakdown`:
  - KPI: 電號數 · 客戶總用電 · 客戶總 RE% · 達標電號數.
  - Table: 電號 · 廠區 · 用電(MWh) · 分配綠電(MWh) · RE%(reCell) · 目標 · 達標(metPill). No-meters → placeholder card.
  - Footnote: "綠電依各電號 RE 目標優先分配(目標較高者優先),Σ各電號綠電 = 客戶總綠電。示範資料。"
- [ ] `node --check`. Local smoke: screenshot `/app/#/meters` for 台積電 showing 台南廠/高雄廠. Commit `feat(meter): 多電號 SPA page`.

---

### Final

- [ ] Full gate. Merge `feat/multi-meter` → main, push SSH.
- [ ] After deploy: run `alembic upgrade head` happens automatically; live smoke `GET /analytics/meter-breakdown?customer_id=1&period=2024-01`.
- [ ] Tell user to re-seed live (Render Shell, one line) so meters appear. Optionally README screenshot.
