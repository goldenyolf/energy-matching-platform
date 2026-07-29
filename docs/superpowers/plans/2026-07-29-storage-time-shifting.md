# 儲能充放（A8 + B5）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 讓客戶側電池把外溢的綠電挪到缺口時段，使逐時 CFE 在「風光」之上再往前推一段。

**Architecture:** `match_hourly` 一行不改——它「嚴格不跨小時」的不變量保持完整。儲能是疊在它輸出之上的獨立純函式層 `app/matching/storage.py`：`apply_storage()` 算充放與 SOC，`with_storage()` 把結果併回成一份新的 `HourlyOutcome`。服務層先跑既有的風光對照（B4），再跑儲能層，於是讀數自然成為三段式：只風電 → 風光 → 風光＋儲。

**Tech Stack:** Python 3.12、SQLAlchemy 2.x（`Mapped`/`mapped_column`）、Alembic、FastAPI + Pydantic v2、pytest；前端為零相依原生 JS SPA（`web/app.js`、`web/styles.css`）。

## Global Constraints

- 規格書：`docs/spec-storage-time-shifting.md`。任何偏離都要記進該檔的「實作結果」節。
- **`app/matching/hourly_matching.py` 不得修改。** 儲能只能是它輸出之上的一層。
- 電池是**客戶側**資產：`batteries.customer_id → customers.id`。
- 充電來源可跨合約，但**自家合約優先**（兩輪）；每筆充電必須記錄來源案場。
- 同一具電池同一小時**不同時充放**：有缺口就放電，無缺口才充電。
- 效率：充電 1:1 進 SOC；放電送出 `SOC × η`，SOC 扣 `送出 / η`。恆等式 `Σ送出 = (期初SOC + Σ充入 − 期末SOC) × η`。
- 新資料表**不得使用 SQLAlchemy `Enum` 欄位**（Neon/Postgres 的 `CREATE TYPE` 陷阱），一律用 `String`／數值。
- 本輪**不動**結算單與 T-REC。
- 每個 task 結束前必須通過完整閘門：`make lint`（ruff + black + mypy）與 `.venv/bin/pytest`。
- 註解與使用者可見文案用繁體中文；程式碼識別字用英文。
- Commit message 用 conventional commits，描述用英文（沿用 repo 慣例）。

---

### Task 1: `batteries` 資料表與 migration

**Files:**
- Create: `app/models/battery.py`
- Modify: `app/models/__init__.py`
- Create: `alembic/versions/f7b3c8d5e2a9_add_batteries.py`
- Test: `tests/unit/test_battery_model.py`

**Interfaces:**
- Consumes: 無（第一個 task）
- Produces: ORM 類別 `app.models.Battery`，欄位 `id, code, customer_id, name, energy_capacity_mwh, power_mw, round_trip_efficiency_percent, initial_soc_percent, created_at, updated_at`

- [ ] **Step 1: 寫失敗的測試**

建立 `tests/unit/test_battery_model.py`：

```python
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
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `.venv/bin/pytest tests/unit/test_battery_model.py -v`
Expected: FAIL — `ImportError: cannot import name 'Battery' from 'app.models'`

- [ ] **Step 3: 建立 ORM model**

建立 `app/models/battery.py`：

```python
"""Battery (客戶側儲能) — a behind-the-meter storage asset owned by a customer.

Storage is what lets green energy cross an hour boundary: it charges from green
that would otherwise spill and discharges into the customer's shortfall. The
matching engine itself stays strictly within-the-hour; see
``app/matching/storage.py`` for the layer that sits on top of its output.

Every column is a String/Float — no SQLAlchemy ``Enum`` — to avoid the Postgres
CREATE TYPE trap on managed deploys (same reason as ``wind_farms.farm_type``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.customer import Customer


class Battery(Base, TimestampMixin):
    __tablename__ = "batteries"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))

    # 容量與功率：充放對稱（power_mw 同時是充電與放電的每小時上限）。
    energy_capacity_mwh: Mapped[float] = mapped_column(Float)
    power_mw: Mapped[float] = mapped_column(Float)
    # 往返效率：充電 1:1 進 SOC、放電送出 SOC × η（損耗一次記在放電端，便於對帳）。
    round_trip_efficiency_percent: Mapped[float] = mapped_column(Float, default=88.0)
    initial_soc_percent: Mapped[float] = mapped_column(Float, default=0.0)

    customer: Mapped[Customer] = relationship()
```

- [ ] **Step 4: 註冊到 model registry**

修改 `app/models/__init__.py`——在 import 區塊（`from app.models.consumption import ConsumptionData` 之前，維持字母序）加入：

```python
from app.models.battery import Battery
```

並在 `__all__` 最前面加入 `"Battery",`。

- [ ] **Step 5: 跑測試確認通過**

Run: `.venv/bin/pytest tests/unit/test_battery_model.py -v`
Expected: PASS（2 passed）

- [ ] **Step 6: 建立 Alembic migration**

建立 `alembic/versions/f7b3c8d5e2a9_add_batteries.py`：

```python
"""add batteries (customer-side storage, A8)

Revision ID: f7b3c8d5e2a9
Revises: e6a2c9d4f1b7
Create Date: 2026-07-29 12:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f7b3c8d5e2a9"
down_revision: str | None = "e6a2c9d4f1b7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "batteries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("energy_capacity_mwh", sa.Float(), nullable=False),
        sa.Column("power_mw", sa.Float(), nullable=False),
        sa.Column("round_trip_efficiency_percent", sa.Float(), nullable=False),
        sa.Column("initial_soc_percent", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_batteries_code", "batteries", ["code"], unique=True)
    op.create_index("ix_batteries_customer_id", "batteries", ["customer_id"])


def downgrade() -> None:
    op.drop_index("ix_batteries_customer_id", table_name="batteries")
    op.drop_index("ix_batteries_code", table_name="batteries")
    op.drop_table("batteries")
```

- [ ] **Step 7: 驗證 migration 可升可降**

Run:
```bash
.venv/bin/alembic upgrade head
.venv/bin/alembic downgrade -1
.venv/bin/alembic upgrade head
```
Expected: 三個指令都成功、無 traceback。（本機 `DATABASE_URL` 未設 → 對 `energy_matching.db` 這顆 SQLite 執行。）

- [ ] **Step 8: 跑完整閘門並提交**

Run: `.venv/bin/pytest && make lint`
Expected: 全數通過。

```bash
git add app/models/battery.py app/models/__init__.py alembic/versions/f7b3c8d5e2a9_add_batteries.py tests/unit/test_battery_model.py
git commit -m "feat(storage): add the batteries table (A8)"
```

---

### Task 2: 電池 CRUD API

**Files:**
- Create: `app/schemas/battery.py`
- Create: `app/services/battery_service.py`
- Create: `app/api/v1/batteries.py`
- Modify: `app/api/v1/router.py`
- Test: `tests/integration/test_batteries_api.py`

**Interfaces:**
- Consumes: `app.models.Battery`（Task 1）
- Produces: REST `/api/v1/batteries`（GET list、POST、GET/{id}、PUT/{id}、DELETE/{id}）；Pydantic `BatteryCreate` / `BatteryUpdate` / `BatteryRead`

- [ ] **Step 1: 寫失敗的測試**

建立 `tests/integration/test_batteries_api.py`：

```python
"""Battery CRUD endpoints (A8)."""

from __future__ import annotations

import pytest

from app.models import Customer


@pytest.fixture()
def customer_id(client, session_factory):
    db = session_factory()
    c = Customer(code="K1", company_name="用電廠一", industry="電源管理")
    db.add(c)
    db.commit()
    cid = c.id
    db.close()
    return cid


def _payload(customer_id: int) -> dict:
    return {
        "code": "BAT-DEMO",
        "customer_id": customer_id,
        "name": "示範儲能",
        "energy_capacity_mwh": 120.0,
        "power_mw": 30.0,
    }


def test_create_then_read_a_battery(client, customer_id):
    created = client.post("/api/v1/batteries", json=_payload(customer_id))
    assert created.status_code == 201
    body = created.json()
    assert body["code"] == "BAT-DEMO"
    assert body["round_trip_efficiency_percent"] == 88.0

    fetched = client.get(f"/api/v1/batteries/{body['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["energy_capacity_mwh"] == 120.0


def test_duplicate_code_is_rejected(client, customer_id):
    client.post("/api/v1/batteries", json=_payload(customer_id))
    again = client.post("/api/v1/batteries", json=_payload(customer_id))
    assert again.status_code == 409


def test_list_can_filter_by_customer(client, customer_id):
    client.post("/api/v1/batteries", json=_payload(customer_id))
    rows = client.get("/api/v1/batteries", params={"customer_id": customer_id}).json()
    assert [r["code"] for r in rows] == ["BAT-DEMO"]
    assert client.get("/api/v1/batteries", params={"customer_id": 99999}).json() == []


def test_update_and_delete(client, customer_id):
    bid = client.post("/api/v1/batteries", json=_payload(customer_id)).json()["id"]

    updated = client.put(f"/api/v1/batteries/{bid}", json={"power_mw": 45.0})
    assert updated.status_code == 200
    assert updated.json()["power_mw"] == 45.0

    assert client.delete(f"/api/v1/batteries/{bid}").status_code == 204
    assert client.get(f"/api/v1/batteries/{bid}").status_code == 404
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `.venv/bin/pytest tests/integration/test_batteries_api.py -v`
Expected: FAIL — 全部 404（路由不存在）

- [ ] **Step 3: 建立 schemas**

建立 `app/schemas/battery.py`：

```python
"""Battery (客戶側儲能) CRUD schemas (A8)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class BatteryBase(BaseModel):
    code: str = Field(..., max_length=50)
    customer_id: int
    name: str = Field(..., max_length=200)
    energy_capacity_mwh: float = Field(..., gt=0)
    power_mw: float = Field(..., gt=0)
    round_trip_efficiency_percent: float = Field(88.0, gt=0, le=100)
    initial_soc_percent: float = Field(0.0, ge=0, le=100)


class BatteryCreate(BatteryBase):
    pass


class BatteryUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    energy_capacity_mwh: float | None = Field(default=None, gt=0)
    power_mw: float | None = Field(default=None, gt=0)
    round_trip_efficiency_percent: float | None = Field(default=None, gt=0, le=100)
    initial_soc_percent: float | None = Field(default=None, ge=0, le=100)


class BatteryRead(BatteryBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime
```

- [ ] **Step 4: 建立 service**

建立 `app/services/battery_service.py`：

```python
"""Battery CRUD (A8). Thin layer over the generic repository, mirroring
``meter_service`` — the storage maths lives in ``app/matching/storage.py``."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError
from app.models import Battery
from app.repositories.base import BaseRepository
from app.schemas.battery import BatteryCreate, BatteryUpdate


def _repo(db: Session) -> BaseRepository[Battery]:
    return BaseRepository(Battery, db)


def create(db: Session, data: BatteryCreate) -> Battery:
    repo = _repo(db)
    if repo.get_by(code=data.code):
        raise ConflictError(f"儲能代碼 '{data.code}' 已存在")
    return repo.create(Battery(**data.model_dump()))


def get(db: Session, battery_id: int) -> Battery:
    row = _repo(db).get(battery_id)
    if row is None:
        raise NotFoundError(f"找不到儲能 id={battery_id}")
    return row


def list_all(
    db: Session,
    *,
    customer_id: int | None = None,
    limit: int = 500,
    offset: int = 0,
) -> list[Battery]:
    stmt = select(Battery).order_by(Battery.id)
    if customer_id is not None:
        stmt = stmt.where(Battery.customer_id == customer_id)
    return list(db.execute(stmt.offset(offset).limit(limit)).scalars().all())


def update(db: Session, battery_id: int, data: BatteryUpdate) -> Battery:
    row = get(db, battery_id)
    return _repo(db).update(row, data.model_dump(exclude_unset=True))


def delete(db: Session, battery_id: int) -> None:
    _repo(db).delete(get(db, battery_id))
```

- [ ] **Step 5: 建立路由**

建立 `app/api/v1/batteries.py`：

```python
"""Battery (客戶側儲能) endpoints (A8)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_write_access
from app.schemas.battery import BatteryCreate, BatteryRead, BatteryUpdate
from app.services import battery_service as svc

router = APIRouter(prefix="/batteries", tags=["batteries"])
_write = Depends(require_write_access)


@router.get("", response_model=list[BatteryRead])
def list_batteries(
    customer_id: int | None = Query(default=None),
    limit: int = Query(500, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    return svc.list_all(db, customer_id=customer_id, limit=limit, offset=offset)


@router.post(
    "",
    response_model=BatteryRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_write],
)
def create_battery(payload: BatteryCreate, db: Session = Depends(get_db)):
    return svc.create(db, payload)


@router.get("/{battery_id}", response_model=BatteryRead)
def get_battery(battery_id: int, db: Session = Depends(get_db)):
    return svc.get(db, battery_id)


@router.put("/{battery_id}", response_model=BatteryRead, dependencies=[_write])
def update_battery(
    battery_id: int, payload: BatteryUpdate, db: Session = Depends(get_db)
):
    return svc.update(db, battery_id, payload)


@router.delete(
    "/{battery_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[_write]
)
def delete_battery(battery_id: int, db: Session = Depends(get_db)) -> None:
    svc.delete(db, battery_id)
```

- [ ] **Step 6: 掛上 router**

修改 `app/api/v1/router.py`：在 `from app.api.v1 import (` 的名單裡加入 `batteries,`（維持字母序，放在 `analytics,` 之後），並在 include 區塊 `api_router.include_router(meters.router)` 之後加入：

```python
api_router.include_router(batteries.router)
```

- [ ] **Step 7: 跑測試確認通過**

Run: `.venv/bin/pytest tests/integration/test_batteries_api.py -v`
Expected: PASS（4 passed）

- [ ] **Step 8: 跑完整閘門並提交**

Run: `.venv/bin/pytest && make lint`

```bash
git add app/schemas/battery.py app/services/battery_service.py app/api/v1/batteries.py app/api/v1/router.py tests/integration/test_batteries_api.py
git commit -m "feat(storage): battery CRUD endpoints"
```

---

### Task 3: 充放核心（`storage.py` 的單電池行為）

**Files:**
- Create: `app/matching/storage.py`
- Test: `tests/unit/test_storage.py`

**Interfaces:**
- Consumes: `app.matching.hourly_matching.HourlyOutcome`（唯讀，不修改該檔）
- Produces:
  - `BatterySpec(battery_id: int, customer_id: int, capacity_mwh: float, power_mw: float, efficiency: float, initial_soc_mwh: float)` — frozen dataclass
  - `StorageOutcome`，欄位：`hours: int`、`charged_by_hour: dict[int, list[float]]`、`discharged_by_hour: dict[int, list[float]]`、`soc_by_hour: dict[int, list[float]]`、`charged_from_farm: dict[int, dict[int, float]]`、`surplus_left_by_hour: dict[int, list[float]]`、`shortfall_left_by_hour: dict[int, list[float]]`
  - `apply_storage(outcome: HourlyOutcome, batteries: list[BatterySpec], farm_customer_order: dict[int, list[int]]) -> StorageOutcome`

- [ ] **Step 1: 寫失敗的測試**

建立 `tests/unit/test_storage.py`：

```python
"""B5 儲能充放層：純函式、確定性、逐步可稽核。"""

from __future__ import annotations

import pytest

from app.matching.hourly_matching import (
    HourlyCustomerResult,
    HourlyFarmResult,
    HourlyOutcome,
)
from app.matching.storage import BatterySpec, apply_storage


def _outcome(surplus: list[float], shortfall: list[float]) -> HourlyOutcome:
    """一座案場、一位客戶的最小 outcome（只有 storage 會讀的那幾個欄位）。"""
    hours = len(surplus)
    out = HourlyOutcome(hours=hours)
    out.farms.append(
        HourlyFarmResult(
            farm_id=1,
            generated_mwh=sum(surplus),
            matched_mwh=0.0,
            surplus_mwh=sum(surplus),
            surplus_by_hour=list(surplus),
        )
    )
    out.customers.append(
        HourlyCustomerResult(
            customer_id=10,
            consumption_mwh=sum(shortfall),
            matched_mwh=0.0,
            cfe_percent=0.0,
            matched_by_hour=[0.0] * hours,
            shortfall_by_hour=list(shortfall),
        )
    )
    return out


def _battery(**kw) -> BatterySpec:
    base = dict(
        battery_id=1,
        customer_id=10,
        capacity_mwh=100.0,
        power_mw=50.0,
        efficiency=1.0,
        initial_soc_mwh=0.0,
    )
    base.update(kw)
    return BatterySpec(**base)


def test_charges_from_surplus_then_discharges_into_shortfall():
    # h0 外溢 40、無缺口 → 充；h1 缺口 40、無外溢 → 放。
    st = apply_storage(_outcome([40.0, 0.0], [0.0, 40.0]), [_battery()], {1: [10]})
    assert st.charged_by_hour[1] == pytest.approx([40.0, 0.0])
    assert st.discharged_by_hour[1] == pytest.approx([0.0, 40.0])
    assert st.soc_by_hour[1] == pytest.approx([40.0, 0.0])
    assert st.shortfall_left_by_hour[10] == pytest.approx([0.0, 0.0])
    assert st.surplus_left_by_hour[1] == pytest.approx([0.0, 0.0])


def test_power_limits_both_charge_and_discharge():
    st = apply_storage(
        _outcome([90.0, 0.0], [0.0, 90.0]), [_battery(power_mw=50.0)], {1: [10]}
    )
    assert st.charged_by_hour[1][0] == pytest.approx(50.0)  # 充電受功率上限
    assert st.discharged_by_hour[1][1] == pytest.approx(50.0)  # 放電同一上限
    assert st.surplus_left_by_hour[1][0] == pytest.approx(40.0)  # 吃不下的仍外溢


def test_capacity_caps_the_stored_energy():
    st = apply_storage(
        _outcome([80.0, 80.0, 0.0], [0.0, 0.0, 500.0]),
        [_battery(capacity_mwh=100.0, power_mw=80.0)],
        {1: [10]},
    )
    assert max(st.soc_by_hour[1]) <= 100.0 + 1e-9
    assert st.charged_by_hour[1] == pytest.approx([80.0, 20.0, 0.0])


def test_a_battery_never_charges_and_discharges_in_the_same_hour():
    # 同一小時既有外溢也有缺口 → 缺口優先,放電,不充電。
    st = apply_storage(
        _outcome([30.0], [30.0]), [_battery(initial_soc_mwh=30.0)], {1: [10]}
    )
    assert st.discharged_by_hour[1][0] == pytest.approx(30.0)
    assert st.charged_by_hour[1][0] == pytest.approx(0.0)
    assert st.surplus_left_by_hour[1][0] == pytest.approx(30.0)  # 外溢原封不動


def test_round_trip_efficiency_is_taken_off_the_discharge():
    st = apply_storage(
        _outcome([100.0, 0.0], [0.0, 100.0]),
        [_battery(efficiency=0.5, power_mw=100.0)],
        {1: [10]},
    )
    assert st.charged_by_hour[1][0] == pytest.approx(100.0)  # 充電 1:1 進 SOC
    assert st.discharged_by_hour[1][1] == pytest.approx(50.0)  # 送出 SOC × η
    assert st.soc_by_hour[1][1] == pytest.approx(0.0)  # SOC 扣 送出/η


def test_energy_conservation_identity_holds():
    b = _battery(efficiency=0.8, initial_soc_mwh=10.0, power_mw=25.0)
    st = apply_storage(
        _outcome([30.0, 0.0, 20.0, 0.0], [0.0, 15.0, 0.0, 40.0]), [b], {1: [10]}
    )
    delivered = sum(st.discharged_by_hour[1])
    charged = sum(st.charged_by_hour[1])
    soc_end = st.soc_by_hour[1][-1]
    # Σ送出 = (期初SOC + Σ充入 − 期末SOC) × η
    assert delivered == pytest.approx((b.initial_soc_mwh + charged - soc_end) * b.efficiency)


def test_soc_carries_across_days():
    # 48 小時：第 1 天充、第 2 天放 → SOC 必須跨日帶過去。
    surplus = [50.0] + [0.0] * 47
    shortfall = [0.0] * 30 + [50.0] + [0.0] * 17
    st = apply_storage(_outcome(surplus, shortfall), [_battery()], {1: [10]})
    assert st.discharged_by_hour[1][30] == pytest.approx(50.0)


def test_is_deterministic():
    args = (_outcome([40.0, 0.0], [0.0, 40.0]), [_battery()], {1: [10]})
    first = apply_storage(*args)
    second = apply_storage(
        _outcome([40.0, 0.0], [0.0, 40.0]), [_battery()], {1: [10]}
    )
    assert first.charged_by_hour == second.charged_by_hour
    assert first.discharged_by_hour == second.discharged_by_hour


def test_no_batteries_leaves_everything_untouched():
    st = apply_storage(_outcome([40.0, 0.0], [0.0, 40.0]), [], {1: [10]})
    assert st.surplus_left_by_hour[1] == pytest.approx([40.0, 0.0])
    assert st.shortfall_left_by_hour[10] == pytest.approx([0.0, 40.0])
    assert st.charged_by_hour == {}
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `.venv/bin/pytest tests/unit/test_storage.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.matching.storage'`

- [ ] **Step 3: 實作 `storage.py`**

建立 `app/matching/storage.py`：

```python
"""B5 — 客戶側儲能充放層（疊在逐時匹配引擎的輸出之上）。

``match_hourly`` 嚴格不跨小時：外溢就是外溢、缺口就是缺口。儲能是唯一能合法
打破這條規則的東西，所以它被做成**獨立的一層**而不是引擎裡的例外——引擎保持
純粹、可稽核、可回歸，這一層負責把外溢的電挪到缺口時段。

每小時的規則（可複述、可稽核）:

1. **放電優先**：客戶在該小時有缺口 → 送出 ``min(缺口, 功率, SOC × η)``，
   SOC 扣 ``送出 / η``。
2. **無缺口才充電**，且同一具電池同一小時不同時充放（物理真實）。充電分兩輪：
   輪 1 只吃「自家有簽約」的案場外溢（依合約優先序），輪 2 才開放其他案場。
3. 每筆充電記錄來自哪座案場（``charged_from_farm``），跨合約的度數流向留得住
   稽核軌跡。

能量守恆恆等式（測試會驗）::

    Σ送出 = (期初 SOC + Σ充入 − 期末 SOC) × η
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.matching.hourly_matching import HourlyOutcome

_EPS = 1e-9


@dataclass(frozen=True)
class BatterySpec:
    """一具電池的物理規格（純資料，無 DB 相依）。"""

    battery_id: int
    customer_id: int
    capacity_mwh: float
    power_mw: float
    efficiency: float  # 往返效率 0–1
    initial_soc_mwh: float = 0.0


@dataclass
class StorageOutcome:
    hours: int
    charged_by_hour: dict[int, list[float]] = field(default_factory=dict)
    discharged_by_hour: dict[int, list[float]] = field(default_factory=dict)
    soc_by_hour: dict[int, list[float]] = field(default_factory=dict)
    # battery_id -> farm_id -> MWh（充電來源歸屬，未來做憑證溯源的地基）
    charged_from_farm: dict[int, dict[int, float]] = field(default_factory=dict)
    surplus_left_by_hour: dict[int, list[float]] = field(default_factory=dict)
    shortfall_left_by_hour: dict[int, list[float]] = field(default_factory=dict)


def apply_storage(
    outcome: HourlyOutcome,
    batteries: list[BatterySpec],
    farm_customer_order: dict[int, list[int]],
) -> StorageOutcome:
    """把外溢挪到缺口時段。``farm_customer_order`` 是每座案場的簽約客戶（依合約
    優先序），用來決定充電輪 1 的先後——沿用引擎排合約的同一把尺。"""
    hours = outcome.hours
    surplus = {f.farm_id: list(f.surplus_by_hour) for f in outcome.farms}
    shortfall = {c.customer_id: list(c.shortfall_by_hour) for c in outcome.customers}
    out = StorageOutcome(
        hours=hours,
        surplus_left_by_hour=surplus,
        shortfall_left_by_hour=shortfall,
    )
    if hours == 0 or not batteries:
        return out

    ordered = sorted(batteries, key=lambda b: b.battery_id)
    by_customer: dict[int, list[BatterySpec]] = {}
    for b in ordered:
        by_customer.setdefault(b.customer_id, []).append(b)
    soc = {
        b.battery_id: min(max(b.initial_soc_mwh, 0.0), b.capacity_mwh) for b in ordered
    }
    for b in ordered:
        out.charged_by_hour[b.battery_id] = [0.0] * hours
        out.discharged_by_hour[b.battery_id] = [0.0] * hours
        out.soc_by_hour[b.battery_id] = [0.0] * hours
        out.charged_from_farm[b.battery_id] = {}

    farm_ids = [f.farm_id for f in outcome.farms]

    def charge(b: BatterySpec, farm_id: int, h: int, busy: set[int]) -> None:
        if b.battery_id in busy or farm_id not in surplus:
            return
        take = min(
            surplus[farm_id][h],
            b.capacity_mwh - soc[b.battery_id],
            b.power_mw - out.charged_by_hour[b.battery_id][h],
        )
        if take <= _EPS:
            return
        surplus[farm_id][h] -= take
        soc[b.battery_id] += take
        out.charged_by_hour[b.battery_id][h] += take
        src = out.charged_from_farm[b.battery_id]
        src[farm_id] = src.get(farm_id, 0.0) + take

    for h in range(hours):
        busy: set[int] = set()  # 這小時已放電的電池,不再充電

        # 1) 放電優先
        for b in ordered:
            load_left = shortfall.get(b.customer_id)
            if load_left is None or load_left[h] <= _EPS:
                continue
            deliver = min(load_left[h], b.power_mw, soc[b.battery_id] * b.efficiency)
            if deliver <= _EPS:
                continue
            soc[b.battery_id] -= deliver / b.efficiency
            load_left[h] -= deliver
            out.discharged_by_hour[b.battery_id][h] += deliver
            busy.add(b.battery_id)

        # 2) 充電輪 1：自家合約的案場外溢（依該案場的合約優先序）
        for farm_id in farm_ids:
            for cid in farm_customer_order.get(farm_id, []):
                for b in by_customer.get(cid, []):
                    charge(b, farm_id, h, busy)

        # 3) 充電輪 2：剩下的外溢才開放給其他電池（依 battery_id）
        for farm_id in farm_ids:
            contracted = set(farm_customer_order.get(farm_id, []))
            for b in ordered:
                if b.customer_id in contracted:
                    continue
                charge(b, farm_id, h, busy)

        for b in ordered:
            out.soc_by_hour[b.battery_id][h] = soc[b.battery_id]

    return out
```

- [ ] **Step 4: 跑測試確認通過**

Run: `.venv/bin/pytest tests/unit/test_storage.py -v`
Expected: PASS（9 passed）

- [ ] **Step 5: 跑完整閘門並提交**

Run: `.venv/bin/pytest && make lint`

```bash
git add app/matching/storage.py tests/unit/test_storage.py
git commit -m "feat(storage): greedy time-sequential charge/discharge layer"
```

---

### Task 4: 兩輪充電優先序與併回 outcome

**Files:**
- Modify: `app/matching/storage.py`（新增 `with_storage`）
- Test: `tests/unit/test_storage_allocation.py`

**Interfaces:**
- Consumes: Task 3 的 `BatterySpec` / `StorageOutcome` / `apply_storage`
- Produces: `with_storage(outcome: HourlyOutcome, storage: StorageOutcome, batteries: list[BatterySpec]) -> HourlyOutcome` — 回傳**新的** outcome，`matched` 加上放電量、`shortfall`／`surplus` 換成剩餘量，所有彙總欄位重算

- [ ] **Step 1: 寫失敗的測試**

建立 `tests/unit/test_storage_allocation.py`：

```python
"""B5 的兩輪充電優先序,以及把充放結果併回 outcome。"""

from __future__ import annotations

import pytest

from app.matching.hourly_matching import (
    HourlyCustomerResult,
    HourlyFarmResult,
    HourlyOutcome,
)
from app.matching.storage import BatterySpec, apply_storage, with_storage


def _outcome(
    farm_surplus: dict[int, list[float]],
    cust_shortfall: dict[int, list[float]],
    cust_matched: dict[int, list[float]] | None = None,
) -> HourlyOutcome:
    hours = len(next(iter(farm_surplus.values())))
    out = HourlyOutcome(hours=hours)
    for fid, sur in farm_surplus.items():
        out.farms.append(
            HourlyFarmResult(
                farm_id=fid,
                generated_mwh=sum(sur),
                matched_mwh=0.0,
                surplus_mwh=sum(sur),
                surplus_by_hour=list(sur),
            )
        )
    for cid, short in cust_shortfall.items():
        matched = list((cust_matched or {}).get(cid, [0.0] * hours))
        out.customers.append(
            HourlyCustomerResult(
                customer_id=cid,
                consumption_mwh=sum(short) + sum(matched),
                matched_mwh=sum(matched),
                cfe_percent=0.0,
                matched_by_hour=matched,
                shortfall_by_hour=list(short),
            )
        )
    out.consumption_by_hour = [
        sum(c.matched_by_hour[h] + c.shortfall_by_hour[h] for c in out.customers)
        for h in range(hours)
    ]
    out.generation_by_hour = [
        sum(f.surplus_by_hour[h] for f in out.farms) for h in range(hours)
    ]
    out.matched_by_hour = [
        sum(c.matched_by_hour[h] for c in out.customers) for h in range(hours)
    ]
    out.surplus_by_hour = list(out.generation_by_hour)
    out.shortfall_by_hour = [
        sum(c.shortfall_by_hour[h] for c in out.customers) for h in range(hours)
    ]
    out.total_consumption_mwh = sum(out.consumption_by_hour)
    out.total_matched_mwh = sum(out.matched_by_hour)
    return out


def _bat(bid: int, cid: int, **kw) -> BatterySpec:
    base = dict(
        battery_id=bid,
        customer_id=cid,
        capacity_mwh=100.0,
        power_mw=100.0,
        efficiency=1.0,
        initial_soc_mwh=0.0,
    )
    base.update(kw)
    return BatterySpec(**base)


def test_own_contract_battery_gets_the_surplus_first():
    # 案場 1 只外溢 30；客戶 10 有簽約、客戶 20 沒有 → 10 先吃滿。
    out = _outcome({1: [30.0]}, {10: [0.0], 20: [0.0]})
    st = apply_storage(out, [_bat(1, 10), _bat(2, 20)], {1: [10]})
    assert st.charged_by_hour[1] == pytest.approx([30.0])
    assert st.charged_by_hour[2] == pytest.approx([0.0])


def test_leftover_surplus_opens_up_to_other_batteries():
    # 案場 1 外溢 130；簽約客戶的電池只吃得下 100 → 剩 30 給沒簽約的。
    out = _outcome({1: [130.0]}, {10: [0.0], 20: [0.0]})
    st = apply_storage(out, [_bat(1, 10, capacity_mwh=100.0), _bat(2, 20)], {1: [10]})
    assert st.charged_by_hour[1] == pytest.approx([100.0])
    assert st.charged_by_hour[2] == pytest.approx([30.0])


def test_contract_order_decides_who_charges_first_on_the_same_farm():
    # 兩位客戶都簽了案場 1,合約優先序是 [20, 10] → 20 先吃。
    out = _outcome({1: [40.0]}, {10: [0.0], 20: [0.0]})
    st = apply_storage(
        out, [_bat(1, 10), _bat(2, 20, capacity_mwh=40.0)], {1: [20, 10]}
    )
    assert st.charged_by_hour[2] == pytest.approx([40.0])
    assert st.charged_by_hour[1] == pytest.approx([0.0])


def test_charge_sources_are_recorded_per_farm():
    out = _outcome({1: [20.0], 2: [50.0]}, {10: [0.0]})
    st = apply_storage(out, [_bat(1, 10)], {1: [10]})
    assert st.charged_from_farm[1] == pytest.approx({1: 20.0, 2: 50.0})


def test_with_storage_moves_discharge_into_matched():
    out = _outcome({1: [40.0, 0.0]}, {10: [0.0, 40.0]}, {10: [60.0, 0.0]})
    bats = [_bat(1, 10)]
    st = apply_storage(out, bats, {1: [10]})

    merged = with_storage(out, st, bats)
    c = merged.customers[0]
    assert c.matched_by_hour == pytest.approx([60.0, 40.0])
    assert c.shortfall_by_hour == pytest.approx([0.0, 0.0])
    assert c.matched_mwh == pytest.approx(100.0)
    assert c.cfe_percent == pytest.approx(100.0)
    assert merged.farms[0].surplus_by_hour == pytest.approx([0.0, 0.0])
    assert merged.cfe_percent == pytest.approx(100.0)


def test_with_storage_leaves_the_original_outcome_alone():
    out = _outcome({1: [40.0, 0.0]}, {10: [0.0, 40.0]}, {10: [60.0, 0.0]})
    bats = [_bat(1, 10)]
    merged = with_storage(out, apply_storage(out, bats, {1: [10]}), bats)

    assert merged is not out
    assert out.customers[0].matched_by_hour == pytest.approx([60.0, 0.0])  # 原件未動
    assert out.customers[0].shortfall_by_hour == pytest.approx([0.0, 40.0])
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `.venv/bin/pytest tests/unit/test_storage_allocation.py -v`
Expected: 前四個測試 PASS（Task 3 已實作兩輪邏輯），後兩個 FAIL — `ImportError: cannot import name 'with_storage'`

- [ ] **Step 3: 實作 `with_storage`**

在 `app/matching/storage.py` 檔尾加入（並把 `HourlyCustomerResult`、`HourlyFarmResult` 加進檔案上方的 import）：

```python
def with_storage(
    outcome: HourlyOutcome,
    storage: StorageOutcome,
    batteries: list[BatterySpec],
) -> HourlyOutcome:
    """把充放結果併回成一份**新的** outcome：放電計入 matched、缺口與外溢換成
    剩餘量、彙總欄位重算。原 outcome 不被修改,呼叫端才留得住「無儲」對照組。"""
    hours = outcome.hours
    delivered: dict[int, list[float]] = {}
    for b in batteries:
        arr = storage.discharged_by_hour.get(b.battery_id)
        if arr is None:
            continue
        tgt = delivered.setdefault(b.customer_id, [0.0] * hours)
        for h, v in enumerate(arr):
            tgt[h] += v

    out = HourlyOutcome(hours=hours)
    for c in outcome.customers:
        extra = delivered.get(c.customer_id, [0.0] * hours)
        matched = [m + x for m, x in zip(c.matched_by_hour, extra, strict=True)]
        matched_mwh = sum(matched)
        out.customers.append(
            HourlyCustomerResult(
                customer_id=c.customer_id,
                consumption_mwh=c.consumption_mwh,
                matched_mwh=matched_mwh,
                cfe_percent=(
                    matched_mwh / c.consumption_mwh * 100.0
                    if c.consumption_mwh > _EPS
                    else 0.0
                ),
                matched_by_hour=matched,
                shortfall_by_hour=list(
                    storage.shortfall_left_by_hour.get(
                        c.customer_id, c.shortfall_by_hour
                    )
                ),
            )
        )
    for f in outcome.farms:
        left = list(storage.surplus_left_by_hour.get(f.farm_id, f.surplus_by_hour))
        surplus_mwh = sum(left)
        out.farms.append(
            HourlyFarmResult(
                farm_id=f.farm_id,
                generated_mwh=f.generated_mwh,
                matched_mwh=f.generated_mwh - surplus_mwh,
                surplus_mwh=surplus_mwh,
                surplus_by_hour=left,
            )
        )

    out.consumption_by_hour = list(outcome.consumption_by_hour)
    out.generation_by_hour = list(outcome.generation_by_hour)
    out.matched_by_hour = [
        sum(c.matched_by_hour[h] for c in out.customers) for h in range(hours)
    ]
    out.surplus_by_hour = [
        sum(f.surplus_by_hour[h] for f in out.farms) for h in range(hours)
    ]
    out.shortfall_by_hour = [
        sum(c.shortfall_by_hour[h] for c in out.customers) for h in range(hours)
    ]
    out.total_consumption_mwh = sum(out.consumption_by_hour)
    out.total_matched_mwh = sum(out.matched_by_hour)
    out.cfe_percent = (
        out.total_matched_mwh / out.total_consumption_mwh * 100.0
        if out.total_consumption_mwh > _EPS
        else 0.0
    )
    return out
```

檔案上方的 import 改為：

```python
from app.matching.hourly_matching import (
    HourlyCustomerResult,
    HourlyFarmResult,
    HourlyOutcome,
)
```

- [ ] **Step 4: 跑測試確認通過**

Run: `.venv/bin/pytest tests/unit/test_storage_allocation.py -v`
Expected: PASS（6 passed）

- [ ] **Step 5: 跑完整閘門並提交**

Run: `.venv/bin/pytest && make lint`

```bash
git add app/matching/storage.py tests/unit/test_storage_allocation.py
git commit -m "feat(storage): two-round charge priority and outcome merge"
```

---

### Task 5: 逐時服務整合與回傳欄位

**Files:**
- Modify: `app/schemas/hourly_matching.py`
- Modify: `app/services/hourly_matching_service.py`
- Test: `tests/integration/test_hourly_storage.py`

**Interfaces:**
- Consumes: Task 1 的 `Battery` model、Task 3/4 的 `BatterySpec` / `apply_storage` / `with_storage`
- Produces: `HourlyMatchingResult` 新增 `no_storage_cfe_percent: float | None`、`storage_uplift_pt: float | None`、`soc_by_hour: list[float] | None`、`discharged_by_hour: list[float] | None`、`charged_by_hour: list[float] | None`；`HourlyCustomerOut` 新增 `no_storage_cfe_percent: float | None`、`storage_uplift_pt: float | None`

**重要順序：** B4 的風光對照（`wind_only_cfe_percent` / `uplift_pt`）必須在儲能層**之前**算完，三段式讀數才成立——`uplift_pt` 是太陽能的貢獻、`storage_uplift_pt` 是儲能的貢獻，兩者不重疊。

- [ ] **Step 1: 寫失敗的測試**

建立 `tests/integration/test_hourly_storage.py`：

```python
"""B5：逐時服務接上客戶側儲能。"""

from __future__ import annotations

from datetime import date

import pytest

from app.models import (
    Battery,
    ConsumptionData,
    Contract,
    Customer,
    GenerationData,
    WindFarm,
)
from app.models.enums import ContractStatus
from app.services import hourly_matching_service as svc


@pytest.fixture()
def seeded_storage(db):
    """夜強日弱的風場 × 日間型負載 → 夜間外溢、白天缺口,正好給電池發揮。"""
    farm = WindFarm(
        code="F1", name="風場一", installed_capacity_mw=100, feed_in_price_per_kwh=4.0
    )
    cust = Customer(
        code="K1", company_name="用電廠一", industry="電源管理", re_target_percent=100.0
    )
    db.add_all([farm, cust])
    db.flush()
    db.add(
        GenerationData(
            wind_farm_id=farm.id,
            period_start=date(2024, 1, 1),
            period_end=date(2024, 1, 31),
            generated_energy_mwh=1000.0,
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
    db.add(
        Contract(
            contract_number="CT-1",
            wind_farm_id=farm.id,
            customer_id=cust.id,
            start_date=date(2024, 1, 1),
            end_date=date(2030, 1, 1),
            status=ContractStatus.ACTIVE,
            price_per_kwh=4.5,
        )
    )
    db.commit()
    return db, farm, cust


def test_no_battery_means_no_storage_readout(seeded_storage):
    db, _, _ = seeded_storage
    res = svc.compute_hourly_outcome(db, "2024-01")
    assert res.no_storage_cfe_percent is None
    assert res.storage_uplift_pt is None
    assert res.soc_by_hour is None
    assert all(c.storage_uplift_pt is None for c in res.customers)


def test_a_battery_lifts_cfe_and_cuts_spill(seeded_storage):
    db, _, cust = seeded_storage
    before = svc.compute_hourly_outcome(db, "2024-01")

    db.add(
        Battery(
            code="BAT-1",
            customer_id=cust.id,
            name="示範儲能",
            energy_capacity_mwh=200.0,
            power_mw=50.0,
        )
    )
    db.commit()
    after = svc.compute_hourly_outcome(db, "2024-01")

    assert after.cfe_percent > before.cfe_percent
    assert after.total_surplus_mwh < before.total_surplus_mwh
    assert after.total_shortfall_mwh < before.total_shortfall_mwh
    # 無儲對照 = 加電池前的數字
    assert after.no_storage_cfe_percent == pytest.approx(before.cfe_percent)
    assert after.storage_uplift_pt == pytest.approx(
        round(after.cfe_percent - before.cfe_percent, 2)
    )


def test_storage_curves_respect_the_battery_limits(seeded_storage):
    db, _, cust = seeded_storage
    db.add(
        Battery(
            code="BAT-1",
            customer_id=cust.id,
            name="示範儲能",
            energy_capacity_mwh=200.0,
            power_mw=50.0,
        )
    )
    db.commit()
    res = svc.compute_hourly_outcome(db, "2024-01")

    assert res.soc_by_hour is not None and len(res.soc_by_hour) == 24
    assert max(res.soc_by_hour) <= 200.0 + 1e-6
    assert res.discharged_by_hour is not None
    assert sum(res.discharged_by_hour) > 0.0
    assert sum(res.charged_by_hour) > 0.0


def test_customer_rows_carry_their_own_storage_uplift(seeded_storage):
    db, _, cust = seeded_storage
    db.add(
        Battery(
            code="BAT-1",
            customer_id=cust.id,
            name="示範儲能",
            energy_capacity_mwh=200.0,
            power_mw=50.0,
        )
    )
    db.commit()
    res = svc.compute_hourly_outcome(db, "2024-01")

    c = next(x for x in res.customers if x.customer_id == cust.id)
    assert c.no_storage_cfe_percent is not None
    assert c.cfe_percent > c.no_storage_cfe_percent
    assert c.storage_uplift_pt == pytest.approx(
        round(c.cfe_percent - c.no_storage_cfe_percent, 2)
    )


def test_storage_also_works_on_the_real_interval_path(seeded_storage):
    """interval 模式跑的是 744 個小時桶,SOC 必須跨日連續、且維持單顆電池的尺度。"""
    from scripts.generate_interval_data import generate

    db, _, cust = seeded_storage
    db.add(
        Battery(
            code="BAT-1",
            customer_id=cust.id,
            name="示範儲能",
            energy_capacity_mwh=200.0,
            power_mw=50.0,
        )
    )
    db.commit()
    generate(db, "2024-01")

    res = svc.compute_hourly_outcome(db, "2024-01")
    assert res.source == "interval"
    assert res.storage_uplift_pt is not None and res.storage_uplift_pt > 0
    # SOC 是日均、不是 31 天的加總 → 不得超過單顆電池的容量。
    assert res.soc_by_hour is not None
    assert max(res.soc_by_hour) <= 200.0 + 1e-6
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `.venv/bin/pytest tests/integration/test_hourly_storage.py -v`
Expected: FAIL — `AttributeError: 'HourlyMatchingResult' object has no attribute 'no_storage_cfe_percent'`

- [ ] **Step 3: 擴充 schema**

修改 `app/schemas/hourly_matching.py`。在 `HourlyCustomerOut` 的 `uplift_pt` 之後加入：

```python
    # 儲能（B5）：加電池之前的同一位客戶 CFE，與電池帶來的增益。
    no_storage_cfe_percent: float | None = None
    storage_uplift_pt: float | None = None
```

在 `HourlyMatchingResult` 的 `solar_generation_by_hour` 之後加入：

```python
    # 儲能（B5）：cfe_percent 已含儲能；no_storage 是加電池前的對照。
    # 三段式讀數＝wind_only → no_storage → cfe_percent。
    no_storage_cfe_percent: float | None = None
    storage_uplift_pt: float | None = None
    soc_by_hour: list[float] | None = None  # 系統合計 SOC（MWh）
    discharged_by_hour: list[float] | None = None
    charged_by_hour: list[float] | None = None
```

- [ ] **Step 4: 服務層接上儲能**

修改 `app/services/hourly_matching_service.py`：

其一，import 區塊加入：

```python
from app.matching.storage import BatterySpec, apply_storage, with_storage
from app.models import Battery
```

（`Battery` 併入既有的 `from app.models import ConsumptionData, Contract, Customer, GenerationData, WindFarm` 那一行，維持字母序。）

其二，在 B4 的風光對照區塊**之後**、`# "帳面" upper bound` 之前插入：

```python
    # 儲能 (B5): 把外溢挪到缺口時段。跑在風光對照之後,三段式讀數才不重疊——
    # uplift_pt 是太陽能的貢獻、storage_uplift_pt 是電池的貢獻。
    battery_rows = list(db.execute(select(Battery).order_by(Battery.id)).scalars())
    no_storage_cfe: float | None = None
    storage_uplift: float | None = None
    soc_series: list[float] | None = None
    discharged_series: list[float] | None = None
    charged_series: list[float] | None = None
    no_storage_by_customer: dict[int, float] = {}
    if battery_rows:
        specs = [
            BatterySpec(
                battery_id=b.id,
                customer_id=b.customer_id,
                capacity_mwh=b.energy_capacity_mwh,
                power_mw=b.power_mw,
                efficiency=b.round_trip_efficiency_percent / 100.0,
                initial_soc_mwh=b.energy_capacity_mwh * b.initial_soc_percent / 100.0,
            )
            for b in battery_rows
        ]
        # 每座案場的簽約客戶,依引擎排合約的同一把尺 → 決定充電輪 1 的先後。
        farm_customer_order: dict[int, list[int]] = {}
        for c in sorted(eligible, key=lambda k: (k.priority, order_rank[k.id], k.id)):
            seen = farm_customer_order.setdefault(c.wind_farm_id, [])
            if c.customer_id not in seen:
                seen.append(c.customer_id)

        storage = apply_storage(outcome, specs, farm_customer_order)
        no_storage_cfe = outcome.cfe_percent
        no_storage_by_customer = {c.customer_id: c.cfe_percent for c in outcome.customers}
        outcome = with_storage(outcome, storage, specs)
        storage_uplift = round(outcome.cfe_percent - no_storage_cfe, 2)

        def _sum_batteries(series: dict[int, list[float]]) -> list[float]:
            total = [0.0] * nb
            for arr in series.values():
                for i, v in enumerate(arr):
                    total[i] += v
            return total

        # 充放是流量 → 跟其他曲線一樣照 reduce24 加總。
        discharged_series = reduce24(_sum_batteries(storage.discharged_by_hour))
        charged_series = reduce24(_sum_batteries(storage.charged_by_hour))
        # SOC 是存量,不能加總——interval 模式下 31 天相加會變成 31 倍容量,
        # 標成 MWh 就是錯的。取同一小時的日均，畫出來才是一顆真實電池的容量尺度。
        soc_series = [v / ndays for v in reduce24(_sum_batteries(storage.soc_by_hour))]
```

其三，逐客戶欄位。在 `customers_out` 的 list comprehension 中，於 `uplift_pt=...` 之後加入：

```python
            no_storage_cfe_percent=no_storage_by_customer.get(c.customer_id)
            if battery_rows
            else None,
            storage_uplift_pt=(
                round(c.cfe_percent - no_storage_by_customer.get(c.customer_id, 0.0), 2)
                if battery_rows
                else None
            ),
```

其四，回傳值。在 `solar_generation_by_hour=solar_by_hour,` 之後加入：

```python
        no_storage_cfe_percent=no_storage_cfe,
        storage_uplift_pt=storage_uplift,
        soc_by_hour=soc_series,
        discharged_by_hour=discharged_series,
        charged_by_hour=charged_series,
```

- [ ] **Step 5: 跑測試確認通過**

Run: `.venv/bin/pytest tests/integration/test_hourly_storage.py -v`
Expected: PASS（5 passed）

- [ ] **Step 6: 確認既有測試沒被破壞**

Run: `.venv/bin/pytest tests/integration/test_hourly_matching_service.py tests/integration/test_hourly_interval.py tests/integration/test_solar_sample_data.py -v`
Expected: 全數 PASS——沒有電池時行為必須與現況完全相同。

- [ ] **Step 7: 跑完整閘門並提交**

Run: `.venv/bin/pytest && make lint`

```bash
git add app/schemas/hourly_matching.py app/services/hourly_matching_service.py tests/integration/test_hourly_storage.py
git commit -m "feat(storage): report the no-storage baseline and storage uplift"
```

---

### Task 6: 示範資料加一具電池

**Files:**
- Create: `data/sample/batteries.csv`
- Modify: `app/ingestion/csv_importer.py`
- Modify: `app/ingestion/sources.py`
- Modify: `scripts/seed.py`
- Test: `tests/integration/test_storage_sample_data.py`

**Interfaces:**
- Consumes: Task 1 的 `Battery` model、Task 5 的服務欄位
- Produces: `csv_importer.import_batteries(db, rows) -> ImportResult`、`CsvDataSource.batteries() -> list[dict]`；示範資料多一具 `BAT-C2`

- [ ] **Step 1: 寫失敗的測試**

建立 `tests/integration/test_storage_sample_data.py`：

```python
"""B5：示範資料帶一具客戶側電池,風光互補之上再加一段。

電池規格取自 2024-01 實測（見 docs/spec-storage-time-shifting.md §4）：
用電廠 2 月缺口約 5,306 MWh、系統單日外溢約 1,547 MWh，充電來源綽綽有餘。
"""

from __future__ import annotations

import pytest

from app.models import Battery, Customer
from app.services import hourly_matching_service as svc


def test_sample_data_has_one_customer_side_battery(seeded_db):
    rows = list(seeded_db.query(Battery))
    assert len(rows) == 1, "示範資料應有 1 具客戶側儲能"
    bat = rows[0]
    assert bat.energy_capacity_mwh == pytest.approx(120.0)
    assert bat.power_mw == pytest.approx(30.0)
    assert bat.round_trip_efficiency_percent == pytest.approx(88.0)


def test_the_battery_belongs_to_the_customer_that_signed_the_solar_ppa(seeded_db):
    bat = seeded_db.query(Battery).one()
    owner = seeded_db.get(Customer, bat.customer_id)
    assert owner.industry == "電源管理"  # 日間型負載,兩輪充電規則都會被走到


def test_storage_lifts_the_demo_portfolio_above_its_no_storage_baseline(seeded_db):
    res = svc.compute_hourly_outcome(seeded_db, "2024-01")
    assert res.no_storage_cfe_percent is not None
    assert res.cfe_percent > res.no_storage_cfe_percent
    assert res.storage_uplift_pt is not None and res.storage_uplift_pt > 0


def test_the_three_segments_are_ordered(seeded_db):
    """只風電 ≤ 風光 ≤ 風光＋儲——每一段各加一件事,不重疊。"""
    res = svc.compute_hourly_outcome(seeded_db, "2024-01")
    assert res.wind_only_cfe_percent is not None
    assert res.no_storage_cfe_percent is not None
    assert res.wind_only_cfe_percent < res.no_storage_cfe_percent < res.cfe_percent
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `.venv/bin/pytest tests/integration/test_storage_sample_data.py -v`
Expected: FAIL — `AssertionError: 示範資料應有 1 具客戶側儲能`（查到 0 筆）

- [ ] **Step 3: 建立示範 CSV**

建立 `data/sample/batteries.csv`：

```csv
code,customer_code,name,energy_capacity_mwh,power_mw,round_trip_efficiency_percent,initial_soc_percent
BAT-C2,CUST-C2,用電廠 2 廠區儲能,120,30,88,0
```

- [ ] **Step 4: 新增 CSV importer**

在 `app/ingestion/csv_importer.py` 的 `import_meters` 之後加入：

```python
def import_batteries(db: Session, rows: Iterable[dict]) -> ImportResult:
    """Batteries (客戶側儲能) reference their customer by *code* in the CSV."""
    from app.models import Battery, Customer

    imported, skipped, errors = 0, 0, []
    for n, row in enumerate(rows, start=2):
        try:
            code = p.s(row.get("code"))
            cust_id = _lookup_id(db, Customer, p.s(row.get("customer_code")))
            if code is None or cust_id is None:
                errors.append(f"row {n}: missing code or unknown customer_code")
                continue
            if _lookup_id(db, Battery, code) is not None:
                skipped += 1
                continue
            db.add(
                Battery(
                    code=code,
                    customer_id=cust_id,
                    name=p.s(row.get("name")) or code,
                    energy_capacity_mwh=p.f(row.get("energy_capacity_mwh")) or 0.0,
                    power_mw=p.f(row.get("power_mw")) or 0.0,
                    round_trip_efficiency_percent=(
                        p.f(row.get("round_trip_efficiency_percent")) or 88.0
                    ),
                    initial_soc_percent=p.f(row.get("initial_soc_percent")) or 0.0,
                )
            )
            db.commit()
            imported += 1
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            errors.append(f"row {n}: {exc}")
    return ImportResult(imported=imported, skipped=skipped, errors=errors)
```

> 先讀 `import_meters` 的實作再動手：`p.s` / `p.f` / `_lookup_id` / `ImportResult` 的用法照抄，例外處理的形狀也要一致。

- [ ] **Step 5: 資料來源加上 batteries()**

修改 `app/ingestion/sources.py`：在 `DataSource` protocol 的 `def meters(self) -> list[dict]: ...` 之後加入 `def batteries(self) -> list[dict]: ...`；在 `CsvDataSource` 的 `meters()` 之後加入：

```python
    def batteries(self) -> list[dict]:
        return self._read("batteries.csv")
```

（`_read` 對不存在的檔案已回傳空 list，所以 `contracts_taipower` 那類其他來源不受影響。）

- [ ] **Step 6: seed 加一步**

修改 `scripts/seed.py`：在 `steps` 清單的 `("meters", ...)` 之後加入：

```python
            ("batteries", csv_importer.import_batteries, source.batteries()),
```

- [ ] **Step 7: 跑測試確認通過**

Run: `.venv/bin/pytest tests/integration/test_storage_sample_data.py -v`
Expected: PASS（4 passed）

- [ ] **Step 8: 重灌本機示範資料並記下實際數字**

Run:
```bash
make seed
.venv/bin/python -c "
from app.db.session import SessionLocal
from app.services import hourly_matching_service as svc
db = SessionLocal()
r = svc.compute_hourly_outcome(db, '2024-01')
print(f'只風電 {r.wind_only_cfe_percent:.2f} → 風光 {r.no_storage_cfe_percent:.2f} → 風光+儲 {r.cfe_percent:.2f}')
print(f'外溢 {r.total_surplus_mwh:.0f} MWh、缺口 {r.total_shortfall_mwh:.0f} MWh')
c = max(r.customers, key=lambda x: x.storage_uplift_pt or 0)
print(f'受惠最大客戶：{c.name} {c.no_storage_cfe_percent:.2f} → {c.cfe_percent:.2f} (+{c.storage_uplift_pt})')
"
```
Expected: 三段遞增；把印出的數字記下來，Task 8 的文件要用。

- [ ] **Step 9: 跑完整閘門並提交**

Run: `.venv/bin/pytest && make lint`

```bash
git add data/sample/batteries.csv app/ingestion/csv_importer.py app/ingestion/sources.py scripts/seed.py tests/integration/test_storage_sample_data.py
git commit -m "feat(data): add a customer-side battery to the demo set"
```

---

### Task 7: 前端三段式讀數、放電斜線帶與 SOC 曲線

**Files:**
- Modify: `web/app.js`
- Modify: `web/styles.css`

**Interfaces:**
- Consumes: Task 5 的回傳欄位 `no_storage_cfe_percent` / `storage_uplift_pt` / `soc_by_hour` / `discharged_by_hour`，以及既有的 `wind_only_cfe_percent` / `uplift_pt`
- Produces: 前端無對外介面（SPA 內部函式 `upliftBar`、`cfeChart`、`socStrip`）

> 前端沒有自動化測試，改動後**必須**用 Playwright 實跑驗證（Step 5），確認 console 無錯誤且元素真的出現。

- [ ] **Step 1: 讀數改成三段式**

修改 `web/app.js` 的 `upliftBar(scope, x)`（在 `cfeHeatmap` 之前）。把整個函式換成：

```js
  // 「只風電 X% → 風光 Y% → 風光＋儲 Z%」讀數；scope 為「全系統」或某一客戶。
  // 每一段各加一件事：太陽能、然後儲能。沒有的那一段自動略過。
  function upliftBar(scope, x) {
    var segs = [];
    if (x.wind_only_cfe_percent != null) segs.push({ lab: "只風電", v: x.wind_only_cfe_percent });
    if (x.no_storage_cfe_percent != null) segs.push({ lab: "風光", v: x.no_storage_cfe_percent });
    segs.push({ lab: segs.length ? "風光＋儲" : "逐時 CFE", v: x.cfe_percent });
    if (segs.length < 2) {
      return '<div class="uplift flat">' + iconInfo() +
        '<span class="up-txt">' + esc(scope) + " 未簽太陽能合約、也沒有儲能，逐時 CFE 不受這兩者影響</span>" +
        infoTip("windSolar") + "</div>";
    }
    var txt = segs.map(function (s, i) {
      return (i ? " → " : "") + esc(s.lab) + " <b>" + pct(s.v) + "%</b>";
    }).join("");
    var pills = "";
    [
      { pt: x.uplift_pt, why: "太陽能" },
      { pt: x.storage_uplift_pt, why: "儲能" },
    ].forEach(function (u) {
      if (u.pt == null) return;
      pills += '<span class="up-pt ' + (u.pt > 0 ? "pos" : "") + '" title="' + u.why + '帶來的增益">' +
        (u.pt > 0 ? "+" : "") + pct(u.pt) + " pt</span>";
    });
    return '<div class="uplift">' + iconInfo() +
      '<span class="up-scope">' + esc(scope) + "</span>" +
      '<span class="up-txt">' + txt + "</span>" + pills +
      '<span class="up-why">正午 bell 補白天缺口，電池再把多餘的挪到早晚</span>' +
      infoTip("windSolar") + "</div>";
  }
```

同時把 `cfeBody(r)` 裡決定要不要顯示這條的判斷（原本是 `r.uplift_pt != null`）改成：

```js
    var uplift = (r.uplift_pt != null || r.storage_uplift_pt != null)
      ? '<div id="cfe-uplift">' + upliftBar("全系統", r) + "</div>"
      : "";
```

- [ ] **Step 2: 24h 圖加放電斜線帶**

修改 `web/app.js` 的 `cfeChart(gen, con, matched, mode, solar)`：

其一，簽名改為 `function cfeChart(gen, con, matched, mode, solar, discharge) {`。

其二，在 `var paths = ...` 之前、`stack` 的 `if` 區塊之後加入：

```js
    // 儲能放電的那一段本來就算在 matched 裡；用斜線帶標出「這一層來自電池」。
    var batt = "";
    if (discharge && discharge.some(function (v) { return v > 0; })) {
      var floor = matched.map(function (m, i) { return Math.max(0, m - (discharge[i] || 0)); });
      batt = '<path d="' + band(floor, matched) + '" class="cfe-batt"/>';
    }
```

其三，`paths` 改為（`batt` 疊在 matched 之上、gen 線之下）：

```js
    var paths = '<path d="' + area(con) + '" class="cfe-demand"/>' +
      '<path d="' + area(matched) + '" class="cfe-match"/>' + batt + stack +
      (gen ? '<path d="' + line(gen) + '" class="cfe-gen"/>' : "");
```

其四，斜線需要一個 SVG pattern。把回傳值的 `<svg ...>` 之後、`grid` 之前插入 defs——即把 return 改為：

```js
    return '<div class="cfe-chart-box"><svg viewBox="0 0 ' + W + " " + Ht + '" role="img" aria-label="24 小時供需匹配圖">' +
      '<defs><pattern id="cfeBattHatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">' +
      '<line x1="0" y1="0" x2="0" y2="6" class="cfe-batt-line"/></pattern></defs>' +
      grid + paths + "</svg></div>";
```

- [ ] **Step 3: 加 SOC 條**

在 `web/app.js` 的 `cfeChart` 之後、`cfeLegend` 之前加入：

```js
  // SOC 走勢條：獨立一條、自己的尺度（與發電/用電量級差很多，不併軸以免誤讀）。
  function socStrip(soc) {
    if (!soc || !soc.some(function (v) { return v > 0; })) return "";
    var H = soc.length, W = 760, Ht = 64, L = 16, R = 12, T = 8, B = 14;
    var pw = W - L - R, ph = Ht - T - B;
    var ymax = Math.max.apply(null, soc) * 1.1 || 1;
    var X = function (i) { return L + (H <= 1 ? 0 : i / (H - 1) * pw); };
    var Y = function (v) { return T + ph - v / ymax * ph; };
    var d = "M" + X(0).toFixed(1) + " " + Y(0).toFixed(1);
    for (var i = 0; i < H; i++) d += " L" + X(i).toFixed(1) + " " + Y(soc[i]).toFixed(1);
    d += " L" + X(H - 1).toFixed(1) + " " + Y(0).toFixed(1) + " Z";
    return '<div class="soc-box"><div class="soc-lab">電池 SOC<small>MWh · 日均</small></div>' +
      '<svg viewBox="0 0 ' + W + " " + Ht + '" role="img" aria-label="電池 SOC 走勢">' +
      '<path d="' + d + '" class="soc-area"/>' +
      '<line x1="' + L + '" y1="' + (T + ph) + '" x2="' + (W - R) + '" y2="' + (T + ph) + '" class="cfe-axis"/>' +
      "</svg></div>";
  }
```

- [ ] **Step 4: 接上 `wireCfe` 與圖例**

修改 `web/app.js` 的 `wireCfe(r)` 的 `draw()`，把 `__all` 分支改為：

```js
      if (v === "__all") {
        wrap.innerHTML = cfeChart(r.generation_by_hour, r.consumption_by_hour, r.matched_by_hour, "all", r.solar_generation_by_hour, r.discharged_by_hour) + socStrip(r.soc_by_hour);
        lg.innerHTML = cfeLegend(true, !!r.solar_generation_by_hour, !!r.discharged_by_hour);
        if (upBox) upBox.innerHTML = upliftBar("全系統", r);
      } else {
```

並把 `cfeLegend` 改為（新增第三個參數）：

```js
  function cfeLegend(withGen, withSolar, withBatt) {
    return '<div class="cfe-lg">' +
      '<span><i class="sw" style="background:var(--good)"></i>已匹配（重疊才算）</span>' +
      '<span><i class="sw" style="background:var(--faint);opacity:.35"></i>缺口（需灰電補足）</span>' +
      (withGen ? '<span><i class="ln"></i>' + (withSolar ? "風光合計發電" : "風電發電") + "（超出用電即外溢）</span>" : "") +
      (withSolar ? '<span><i class="ln ln-wind"></i>只風電</span><span><i class="sw sw-solar"></i>太陽能補上的部分</span>' : "") +
      (withBatt ? '<span><i class="sw sw-batt"></i>儲能放電</span>' : "") +
      '<span class="cfe-hint">' + (withGen
        ? (withBatt ? "斜線那層是電池放出來的電——原本會外溢，被挪到缺口時段" : (withSolar ? "午間那條琥珀色帶就是太陽能填進風電的白天缺口（風光互補）" : "綠色越貼齊用電輪廓，時間匹配越好"))
        : "此客戶：綠色＝已匹配、上方灰色＝該時段仍需灰電") + "</span></div>";
  }
```

其餘呼叫 `cfeLegend(false)` 的地方不必改（多餘參數自動為 `undefined`）。

再修改 `INFO` 物件——在 `windSolar` 之後加入儲能說明卡：

```js
    storage: {
      title: "儲能時間位移",
      html:
        "<p>逐時匹配的鐵律是<b>嚴格不跨小時</b>：發電時沒人用就是外溢、用電時沒電就是缺口，兩邊不能互抵。</p>" +
        "<p><b>儲能</b>是唯一能合法打破這條鐵律的東西——把外溢的綠電充進電池，等缺口出現再放出來。放電會有往返效率損耗（示範為 88%）。</p>" +
        '<p class="tip-eg">示範中電池可收任一案場的外溢（自家合約優先），屬<b>情境模擬</b>——實務上跨案場取電需另簽轉供合約。結算與 T-REC 尚未反映充放。</p>',
    },
```

並把 `upliftBar` 裡兩處 `infoTip("windSolar")` 中、有儲能那一版的說明改指向新卡：把上方 Step 1 程式碼裡 `infoTip("windSolar") + "</div>";`（非 `flat` 那一行）改為：

```js
      (x.storage_uplift_pt != null ? infoTip("storage") : infoTip("windSolar")) + "</div>";
```

- [ ] **Step 5: 加樣式**

修改 `web/styles.css`。在 `.cfe-solar{...}` 之後加入：

```css
.cfe-batt{fill:url(#cfeBattHatch);stroke:var(--buyer);stroke-width:.6;stroke-opacity:.5}
.cfe-batt-line{stroke:var(--buyer);stroke-width:2.4;opacity:.55}
```

在 `.cfe-lg .sw-solar{...}` 之後加入：

```css
.cfe-lg .sw-batt{background:repeating-linear-gradient(45deg,var(--buyer),var(--buyer) 2px,transparent 2px,transparent 4px);opacity:.75}
```

在 `.uplift .up-why{...}` 之前加入（多顆增益 pill 的間距）：

```css
.uplift .up-pt + .up-pt{margin-left:-4px}
```

在 `.gapbar{...}` 之前加入 SOC 條樣式：

```css
/* 電池 SOC 走勢條（獨立尺度，不與發電量併軸） */
.soc-box{margin:2px 8px 6px;padding-top:4px;border-top:1px dashed var(--line)}
.soc-box .soc-lab{font-size:11px;color:var(--muted);padding-left:8px}
.soc-box .soc-lab small{margin-left:4px;color:var(--faint)}
.soc-box svg{width:100%;height:auto;display:block}
.soc-area{fill:var(--buyer);fill-opacity:.22;stroke:var(--buyer);stroke-width:1.4}
```

- [ ] **Step 6: 用 Playwright 實跑驗證**

先起服務：`.venv/bin/uvicorn app.main:app --port 8123`（背景執行）。

建立臨時腳本（放 scratchpad，不要進 repo），對 `http://127.0.0.1:8123/#cfe` 截圖並檢查：

```js
const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1280, height: 1000 } });
  const errs = [];
  page.on('console', m => { if (m.type() === 'error') errs.push(m.text()); });
  page.on('pageerror', e => errs.push('pageerror: ' + e.message));
  await page.goto('http://127.0.0.1:8123/#cfe', { waitUntil: 'networkidle' });
  await page.waitForSelector('.uplift');
  await page.waitForTimeout(2000);
  await page.screenshot({ path: 'cfe-storage.png' });
  console.log('UPLIFT:', (await page.locator('.uplift').first().innerText()).replace(/\n/g, ' | '));
  console.log('SOC 條:', await page.locator('.soc-box').count());
  console.log('放電斜線帶:', await page.locator('path.cfe-batt').count());
  console.log('ERRORS:', errs.length ? errs : 'none');
  await browser.close();
})();
```

Expected：讀數三段（只風電 → 風光 → 風光＋儲）、兩顆 pt pill、`SOC 條: 1`、`放電斜線帶: 1`、`ERRORS: none`。看一眼截圖確認斜線帶在合理位置、SOC 條沒有壓到別的元素。

- [ ] **Step 7: 檢查 JS 語法並提交**

Run: `node --check web/app.js && .venv/bin/pytest && make lint`

```bash
git add web/app.js web/styles.css
git commit -m "feat(web): three-segment CFE readout, discharge band and SOC strip"
```

---

### Task 8: 文件與 roadmap 收尾

**Files:**
- Modify: `docs/spec-storage-time-shifting.md`
- Modify: `docs/roadmap-data.js`
- Modify: `README.md`
- Modify: `docs/images/cfe-hourly.png`

**Interfaces:**
- Consumes: Task 6 Step 8 記下的實際數字、Task 7 的畫面
- Produces: 無程式介面

- [ ] **Step 1: spec 補上實作結果**

在 `docs/spec-storage-time-shifting.md` 的 `## 10. 未來延伸` 之前插入 `## 11. 實作結果（YYYY-MM-DD）`，內容包含：Task 6 Step 8 印出的三段數字與受惠最大的客戶、外溢下降幅度、閘門結果（`N passed`）、以及**任何與 §2–§6 的偏離**（照 `spec-wind-solar-complementarity.md` §11 的表格格式：項目／規劃／實作／原因）。並把檔頭狀態改為 `✅ 已實作（YYYY-MM-DD）`。

- [ ] **Step 2: roadmap 標記完成**

修改 `docs/roadmap-data.js`，在 `byId['A7'].done = true; byId['B4'].done = true;` 之後加入：

```js
  // 儲能：A8 電池實體（batteries 表）+ B5 客戶側充放層（貪婪時序、兩輪充電優先序）
  // 與三段式讀數（只風電 → 風光 → 風光＋儲）已上線。
  byId['A8'].done = true; byId['B5'].done = true;
```

Run: `node --check docs/roadmap-data.js`

- [ ] **Step 3: 重拍 README 截圖**

服務仍在 8123 埠時，用 Playwright 以 1440 寬、`deviceScaleFactor: 2`、`colorScheme: 'light'`、`fullPage: true` 覆蓋 `docs/images/cfe-hourly.png`（既有截圖即為此規格）。拍完用 Read 看一眼，確認三段讀數、斜線帶、SOC 條都在畫面上。

- [ ] **Step 4: README 補段落並更新數字**

修改 `README.md`：

- 「功能」清單裡逐時那一條，補上儲能：`…並直接給出「只風電 vs 風光 vs 風光＋儲」的 CFE 增益（系統級與逐客戶）。`
- 在「**風光互補**」段落之後新增一段 **儲能時間位移**：說明鐵律（嚴格不跨小時）、電池是唯一能合法打破它的東西、`match_hourly` 一行未改、三段式讀數（填入實際數字）、斜線帶與 SOC 條、以及跨合約充電屬情境模擬且結算/T-REC 未反映。
- 檢查「逐時（24/7 CFE）匹配」段落內引用的數字是否仍成立（示範資料多了電池，系統 CFE 會變）——如有出入一併更新。

- [ ] **Step 5: 最終閘門並提交**

Run: `.venv/bin/pytest && make lint && node --check web/app.js && node --check docs/roadmap-data.js`

```bash
git add docs/spec-storage-time-shifting.md docs/roadmap-data.js README.md docs/images/cfe-hourly.png
git commit -m "docs: mark A8/B5 done and record the storage results"
```

- [ ] **Step 6: 關閉背景服務**

Run: `pkill -f "uvicorn app.main:app --port 8123"`
