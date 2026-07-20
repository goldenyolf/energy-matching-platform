# T-REC 憑證追蹤 Implementation Plan

> REQUIRED SUB-SKILL: superpowers:executing-plans.

**Goal:** Persisted T-REC batches, two-stage lifecycle (issue+transfer via matching → retire), ledger + write endpoints + interactive SPA.

## Global Constraints

- Full gate: `ruff` · `black` · **`mypy app`** · `pytest` · `node --check`. Migration on SQLite + Postgres.
- `status` is a plain `String` column ("transferred"/"retired") — NO DB enum.
- 1 T-REC = 1 MWh. SSH push, per-task commits.

---

### Task 1: Model + migration

**Files:** create `app/models/trec.py`; modify `app/models/enums.py`, `app/models/__init__.py`; create `alembic/versions/<rev>_add_trec_batches.py`; test `tests/integration/test_trec_model.py`.

- [ ] **Step 1: failing test** `tests/integration/test_trec_model.py`:

```python
from datetime import date
from app.models import Customer, TrecBatch, WindFarm


def test_trec_batch_persists(db):
    f = WindFarm(code="WF", name="F", installed_capacity_mw=10)
    c = Customer(code="CU", company_name="X")
    db.add_all([f, c]); db.flush()
    b = TrecBatch(batch_no="TREC-2024-01-WF-CU", wind_farm_id=f.id, customer_id=c.id, period="2024-01", quantity_mwh=100.0, status="transferred")
    db.add(b); db.commit()
    got = db.query(TrecBatch).one()
    assert got.status == "transferred" and got.wind_farm.code == "WF" and got.customer.code == "CU"
```

- [ ] **Step 2:** run → FAIL. **Step 3:** `app/models/enums.py` add:

```python
class TrecStatus(StrEnum):
    TRANSFERRED = "transferred"
    RETIRED = "retired"
```

- [ ] **Step 4:** `app/models/trec.py`:

```python
"""T-REC certificate batch (1 憑證 = 1 MWh)."""

from __future__ import annotations

from sqlalchemy import Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.models.customer import Customer
from app.models.wind_farm import WindFarm


class TrecBatch(Base, TimestampMixin):
    __tablename__ = "trec_batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_no: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    wind_farm_id: Mapped[int] = mapped_column(ForeignKey("wind_farms.id"), index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    period: Mapped[str] = mapped_column(String(7), index=True)
    quantity_mwh: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(20), default="transferred")

    wind_farm: Mapped[WindFarm] = relationship()
    customer: Mapped[Customer] = relationship()
```

- [ ] **Step 5:** `app/models/__init__.py`: export `TrecBatch`, `TrecStatus`. Run test → PASS.

- [ ] **Step 6:** `alembic revision -m "add trec_batches"`; edit `upgrade`/`downgrade`:

```python
def upgrade() -> None:
    op.create_table(
        "trec_batches",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("batch_no", sa.String(length=120), nullable=False),
        sa.Column("wind_farm_id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("period", sa.String(length=7), nullable=False),
        sa.Column("quantity_mwh", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["wind_farm_id"], ["wind_farms.id"]),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_trec_batches_batch_no"), "trec_batches", ["batch_no"], unique=True)
    op.create_index(op.f("ix_trec_batches_wind_farm_id"), "trec_batches", ["wind_farm_id"])
    op.create_index(op.f("ix_trec_batches_customer_id"), "trec_batches", ["customer_id"])
    op.create_index(op.f("ix_trec_batches_period"), "trec_batches", ["period"])


def downgrade() -> None:
    op.drop_index(op.f("ix_trec_batches_period"), table_name="trec_batches")
    op.drop_index(op.f("ix_trec_batches_customer_id"), table_name="trec_batches")
    op.drop_index(op.f("ix_trec_batches_wind_farm_id"), table_name="trec_batches")
    op.drop_index(op.f("ix_trec_batches_batch_no"), table_name="trec_batches")
    op.drop_table("trec_batches")
```
Set `down_revision = "0f179db933d6"`.

- [ ] **Step 7:** verify round-trip on scratch SQLite (`DATABASE_URL=sqlite:///./_t.db alembic upgrade head && downgrade -1 && upgrade head; rm _t.db`). Gate. Commit `feat(trec): TrecBatch model + migration`.

---

### Task 2: Schema + service (TDD)

**Files:** create `app/schemas/trec.py`, `app/services/trec_service.py`; test `tests/integration/test_trec.py`.

- [ ] **Step 1: failing tests** — seed farm+customer+contract+generation+consumption so a period matches; `issue_for_period` creates ≥1 batch, idempotent (2nd → 0); `retire` flips status; `get_ledger` summary consistent (`transferred_mwh + retired_mwh == total_quantity_mwh`).

```python
from datetime import date
import pytest
from app.models import ConsumptionData, Contract, Customer, GenerationData, WindFarm
from app.models.enums import ContractStatus
from app.services.trec_service import get_ledger, issue_for_period, retire


def _seed(db):
    f = WindFarm(code="WF", name="F", installed_capacity_mw=100, feed_in_price_per_kwh=4.0)
    c = Customer(code="CU", company_name="X", re_target_percent=50.0)
    db.add_all([f, c]); db.flush()
    db.add(GenerationData(wind_farm_id=f.id, period_start=date(2024,1,1), period_end=date(2024,1,31), generated_energy_mwh=300.0))
    db.add(ConsumptionData(customer_id=c.id, period_start=date(2024,1,1), period_end=date(2024,1,31), consumed_energy_mwh=500.0))
    db.add(Contract(contract_number="C1", wind_farm_id=f.id, customer_id=c.id, start_date=date(2024,1,1), end_date=date(2030,12,31), status=ContractStatus.ACTIVE, priority=1, contracted_percentage=100.0, price_per_kwh=5.0))
    db.commit(); return f, c


def test_issue_idempotent_and_retire(db):
    _seed(db)
    n = issue_for_period(db, "2024-01")
    assert n >= 1
    assert issue_for_period(db, "2024-01") == 0  # idempotent
    led = get_ledger(db, period="2024-01")
    assert led.summary.total_batches == n
    assert led.summary.transferred_mwh > 0 and led.summary.retired_mwh == 0
    batch_id = led.batches[0].id
    retire(db, batch_id)
    led2 = get_ledger(db, period="2024-01")
    assert led2.summary.retired_batches == 1
    assert led2.summary.transferred_mwh + led2.summary.retired_mwh == pytest.approx(led2.summary.total_quantity_mwh)


def test_retire_unknown_raises(db):
    from app.core.exceptions import NotFoundError
    with pytest.raises(NotFoundError):
        retire(db, 999999)
```

- [ ] **Step 2:** run → FAIL. **Step 3:** `app/schemas/trec.py` (per spec). **Step 4:** `app/services/trec_service.py`:

```python
"""T-REC certificate lifecycle: issue+transfer from matching, retire, ledger."""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.models import Contract, Customer, TrecBatch, WindFarm
from app.models.enums import TrecStatus
from app.schemas.trec import TrecBatchOut, TrecLedger, TrecSummary
from app.services.matching_service import compute_outcome


def issue_for_period(db: Session, period: str) -> int:
    outcome = compute_outcome(db, period)
    contracts = {c.id: c for c in db.execute(select(Contract)).scalars()}
    farms = {f.id: f for f in db.execute(select(WindFarm)).scalars()}
    custs = {c.id: c for c in db.execute(select(Customer)).scalars()}
    existing = {
        (b.wind_farm_id, b.customer_id)
        for b in db.execute(
            select(TrecBatch).where(TrecBatch.period == period)
        ).scalars()
    }
    qty: dict[tuple[int, int], float] = defaultdict(float)
    for a in outcome.allocations:
        if a.allocated_mwh <= 1e-9:
            continue
        c = contracts.get(a.contract_id)
        if c is None:
            continue
        qty[(c.wind_farm_id, c.customer_id)] += a.allocated_mwh
    created = 0
    for (farm_id, cust_id), q in qty.items():
        if (farm_id, cust_id) in existing:
            continue
        fc = farms[farm_id].code if farm_id in farms else farm_id
        cc = custs[cust_id].code if cust_id in custs else cust_id
        db.add(
            TrecBatch(
                batch_no=f"TREC-{period}-{fc}-{cc}",
                wind_farm_id=farm_id,
                customer_id=cust_id,
                period=period,
                quantity_mwh=round(q, 3),
                status=TrecStatus.TRANSFERRED.value,
            )
        )
        created += 1
    db.commit()
    return created


def retire(db: Session, batch_id: int) -> TrecBatch:
    b = db.get(TrecBatch, batch_id)
    if b is None:
        raise NotFoundError(f"T-REC batch {batch_id} not found")
    b.status = TrecStatus.RETIRED.value
    db.commit()
    db.refresh(b)
    return b


def _row(b: TrecBatch) -> TrecBatchOut:
    return TrecBatchOut(
        id=b.id,
        batch_no=b.batch_no,
        wind_farm_code=b.wind_farm.code,
        wind_farm_name=b.wind_farm.name,
        customer_code=b.customer.code,
        company_name=b.customer.company_name,
        period=b.period,
        quantity_mwh=round(b.quantity_mwh, 3),
        status=b.status,
    )


def get_ledger(
    db: Session, period: str | None = None, customer_id: int | None = None
) -> TrecLedger:
    stmt = select(TrecBatch)
    if period:
        stmt = stmt.where(TrecBatch.period == period)
    if customer_id:
        stmt = stmt.where(TrecBatch.customer_id == customer_id)
    batches = list(db.execute(stmt.order_by(TrecBatch.id.desc())).scalars())
    transferred = [b for b in batches if b.status == TrecStatus.TRANSFERRED.value]
    retired = [b for b in batches if b.status == TrecStatus.RETIRED.value]
    t_mwh = round(sum(b.quantity_mwh for b in transferred), 3)
    r_mwh = round(sum(b.quantity_mwh for b in retired), 3)
    return TrecLedger(
        period=period,
        summary=TrecSummary(
            total_batches=len(batches),
            total_quantity_mwh=round(t_mwh + r_mwh, 3),
            transferred_mwh=t_mwh,
            retired_mwh=r_mwh,
            transferred_batches=len(transferred),
            retired_batches=len(retired),
        ),
        batches=[_row(b) for b in batches],
    )
```

- [ ] **Step 5:** run → PASS. Gate. Commit `feat(trec): certificate service + schema`.

---

### Task 3: Endpoints (new router) + API tests

**Files:** create `app/api/v1/trecs.py`; modify `app/api/v1/router.py`; test `tests/integration/test_trec_api.py`.

- [ ] `app/api/v1/trecs.py`:

```python
"""T-REC certificate endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.schemas.trec import TrecBatchOut, TrecLedger
from app.services import trec_service as svc

router = APIRouter(prefix="/trecs", tags=["trecs"])


@router.get("", response_model=TrecLedger)
def ledger(
    period: str | None = Query(None, examples=["2024-01"]),
    customer_id: int | None = Query(None, ge=1),
    db: Session = Depends(get_db),
) -> TrecLedger:
    return svc.get_ledger(db, period=period, customer_id=customer_id)


@router.post("/issue", response_model=TrecLedger)
def issue(
    period: str = Query(..., examples=["2024-01"]),
    db: Session = Depends(get_db),
) -> TrecLedger:
    svc.issue_for_period(db, period)
    return svc.get_ledger(db, period=period)


@router.post("/{batch_id}/retire", response_model=TrecBatchOut)
def retire_batch(batch_id: int, db: Session = Depends(get_db)) -> TrecBatchOut:
    b = svc.retire(db, batch_id)
    return svc._row(b)
```

- [ ] Register in `app/api/v1/router.py` (include `trecs.router`).
- [ ] `tests/integration/test_trec_api.py`: POST `/api/v1/trecs/issue?period=2024-01` → 200, batches created; GET `/api/v1/trecs?period=2024-01` → summary; POST `/api/v1/trecs/{id}/retire` → status retired; retire unknown → 404.
- [ ] Gate. Commit `feat(trec): certificate endpoints`.

---

### Task 4: Seed integration

**Files:** modify `scripts/seed.py`; test `tests/integration/test_trec.py` (add a seed-path assertion is optional — covered by service tests).

- [ ] `scripts/seed.py` (sample path, after meters split): `from app.services.trec_service import issue_for_period, retire` (local import inside seed to avoid heavy import at module load is fine); `issue_for_period(db, "2024-01")`; retire the two most-recent batches (query 2, retire) to show both statuses; print `T-REC 憑證   : 已由 2024-01 媒合結果發行`.
- [ ] Re-seed local; verify ledger populated (some transferred + some retired). Gate. Commit `chore(trec): issue demo certificates in seed`.

---

### Task 5: SPA page (+ post helper)

**Files:** modify `web/api.js`, `web/index.html`, `web/app.js`.

- [ ] `web/api.js`: add `post(path, params)` (fetch `method:"POST"`, same ok/JSON/error handling as `get`, no body — params in query string via `qs`). Methods: `trecs(period, customerId)` (GET), `trecsIssue(period)` (POST `/trecs/issue`), `trecRetire(batchId)` (POST `/trecs/{id}/retire`).
- [ ] `web/index.html`: nav under 監控/結算, after 轉供結算: `<a data-route="trecs">…T-REC 憑證</a>`.
- [ ] `web/app.js`: router `trecs: renderTrecs`; `renderTrecs`:
  - Controls card: 期間 input + 「發行本期憑證」btn (→ `api.trecsIssue(period)` → re-render) .
  - KPI: 總憑證(MWh) · 已移轉 · 已註銷 · 批次數.
  - Table: 批次號 · 風場 · 客戶 · 年份別 · 數量(MWh) · 狀態(pill 已移轉 warnp / 已註銷 ok) · 動作(「註銷」btn for transferred → `api.trecRetire(id)` → re-render). Empty → hint.
  - Footnote (1 憑證=1MWh; 註銷不可再交易). Use event delegation for the dynamic retire buttons (data-id attr).
- [ ] `node --check`. Local smoke: screenshot `/app/#/trecs` (after seed). Commit `feat(trec): T-REC SPA page`.

---

### Final

- [ ] Full gate. Merge `feat/trec` → main, push SSH.
- [ ] After deploy (migration auto-applies): POST `/api/v1/trecs/issue?period=2024-01` to populate live (or the SEED_ON_START toggle already issued via seed); live smoke GET ledger.
- [ ] Optionally README screenshot.
