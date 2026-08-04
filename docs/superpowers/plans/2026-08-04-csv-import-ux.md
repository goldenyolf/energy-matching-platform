# 自助 CSV 匯入強化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 讓 CSV 匯入在按下去之前就看得見結果（新增／更新／略過／錯誤逐列可讀），並讓欄位清單只有一份真相。

**Architecture:** 新增一份宣告式欄位表 `app/ingestion/schema.py`，同時餵給 importer、範本下載、UI 欄位說明與錯誤訊息。匯入改走共用管線 `run_import()`，每列包自己的 SAVEPOINT；dry-run 綁在外層 session 的連線上開 SAVEPOINT，跑**完全相同**的寫入路徑後退回，因此預覽與真匯入不可能不一致。

**Tech Stack:** Python 3.12、FastAPI、SQLAlchemy 2.x、Pydantic v2、pytest；前端是零依賴原生 JS（`web/app.js`、`web/api.js`）。

## Global Constraints

- **設計文件**：`docs/superpowers/specs/2026-08-04-csv-import-ux-design.md`。有衝突以 spec 為準。
- **CI 閘門**（每次 commit 前都要能過）：
  - `.venv/bin/ruff check app tests`
  - `.venv/bin/black --check app tests`
  - `.venv/bin/mypy app`
  - `.venv/bin/pytest --cov=app --cov-report=term-missing --cov-fail-under=90`
  - lint／format 的範圍是 `app tests`，**不是 `.`**；`alembic/` 有既有 drift，不要順手修。
- **不要動**：`app/matching/*`（匹配引擎與本次無關）、`app/services/*` 的寫入語意（upsert 走 importer 層）。
- **語言**：所有面向使用者的字串一律**繁體中文**。程式碼註解沿用檔案現有語言。
- **相容性**：`ImportResult.imported` / `skipped` / `errors` 三個既有欄位的型別與意義不得改變。`tests/integration/test_taipower_contracts.py` 現有斷言必須維持綠燈，**不准為了讓它過而修改該測試**。
- **不新增第三方依賴。**
- **提交訊息**：Conventional Commits，結尾加
  `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`

## 檔案結構

| 檔案 | 責任 |
|---|---|
| `app/ingestion/schema.py`（新） | 欄位表單一真相：`Column` / `EntitySpec` / `SPECS` |
| `app/ingestion/template.py`（新） | 由 spec 產生範本 CSV 位元組（含 BOM） |
| `app/ingestion/pipeline.py`（新） | `dry_run_session()` ＋ `run_import()` 共用管線 |
| `app/ingestion/csv_importer.py`（改） | 七個 importer 改為提供 handler，迴圈交給 pipeline |
| `app/ingestion/parsing.py`（改） | 解析失敗帶欄位脈絡與中文訊息 |
| `app/schemas/common.py`（改） | `RowResult` / `ErrorGroup` / 擴充 `ImportResult` |
| `app/api/v1/imports.py`（新） | `GET /import/schema`、`GET /import/template/{entity}` |
| `app/api/v1/*.py`（改） | 六個 `/import` 加 `dry_run`；`batteries` 補 `/import` |
| `web/api.js`、`web/app.js`、`web/styles.css`（改） | 預覽面板 |

任務順序刻意讓**每一個 task 結束時測試都是綠的**，且前四個 task 完全不碰前端。

---

### Task 1: dry-run 隔離機制（整個設計的支點）

先做這個，因為其餘所有東西都建立在「dry-run 真的不落地」之上。這一步已經在設計階段用 probe 驗過可行，這裡是把它變成受測程式碼。

**Files:**
- Create: `app/ingestion/pipeline.py`
- Test: `tests/integration/test_import_dry_run.py`

**Interfaces:**
- Consumes: 無
- Produces: `dry_run_session(db: Session) -> ContextManager[Session]`

- [ ] **Step 1: 寫失敗的測試**

`tests/integration/test_import_dry_run.py`：

```python
"""Dry-run 必須跑真正的寫入路徑，然後不留任何痕跡。"""

from __future__ import annotations

from sqlalchemy import select

from app.ingestion.pipeline import dry_run_session
from app.models import Customer
from app.schemas.customer import CustomerCreate
from app.services import customers as customer_svc


def _payload(code: str) -> CustomerCreate:
    return CustomerCreate(
        code=code,
        company_name=code,
        annual_consumption_mwh=1.0,
        re_target_percent=10.0,
    )


def test_dry_run_leaves_no_trace(db):
    customer_svc.create(db, _payload("C-REAL"))

    with dry_run_session(db) as scoped:
        customer_svc.create(scoped, _payload("C-DRY"))
        inside = scoped.execute(select(Customer.code)).scalars().all()

    assert "C-DRY" in inside, "dry-run 之內應該看得到自己寫的資料"
    after = db.execute(select(Customer.code)).scalars().all()
    assert after == ["C-REAL"], f"dry-run 洩漏到真實資料庫: {after}"


def test_outer_session_still_writable_after_dry_run(db):
    with dry_run_session(db) as scoped:
        customer_svc.create(scoped, _payload("C-DRY"))

    customer_svc.create(db, _payload("C-AFTER"))
    codes = sorted(db.execute(select(Customer.code)).scalars().all())
    assert codes == ["C-AFTER"]


def test_failed_row_does_not_poison_the_rest(db):
    """單列失敗後，同一 session 仍能繼續寫入後面的列（Postgres 的必要條件）。"""
    done: list[str] = []
    with dry_run_session(db) as scoped:
        for code in ["A", "BAD", "C"]:
            nested = scoped.begin_nested()
            try:
                if code == "BAD":
                    raise ValueError("simulated")
                customer_svc.create(scoped, _payload(code))
                done.append(code)
            except ValueError:
                if nested.is_active:
                    nested.rollback()
    assert done == ["A", "C"]
```

- [ ] **Step 2: 跑測試確認它失敗**

Run: `.venv/bin/pytest tests/integration/test_import_dry_run.py -v`
Expected: FAIL —`ModuleNotFoundError: No module named 'app.ingestion.pipeline'`

- [ ] **Step 3: 寫最小實作**

`app/ingestion/pipeline.py`：

```python
"""共用匯入管線：dry-run 隔離與逐列執行骨架。"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy.orm import Session, sessionmaker


@contextmanager
def dry_run_session(db: Session) -> Iterator[Session]:
    """在外層 session 自己的連線上開一個 SAVEPOINT，離開時退回。

    綁在同一條連線是刻意的：測試用 ``sqlite://`` ＋ ``StaticPool``，整個
    engine 共用一條 DBAPI 連線，另開連線會撞上「cannot start a transaction
    within a transaction」。``join_transaction_mode="create_savepoint"`` 讓
    ``BaseRepository.create()`` 內部的 ``commit()`` 只是釋放 SAVEPOINT，
    外層不受影響——所以 dry-run 走的是與真匯入完全相同的寫入路徑。
    """
    conn = db.connection()
    savepoint = conn.begin_nested()
    factory = sessionmaker(bind=conn, join_transaction_mode="create_savepoint")
    scoped = factory()
    try:
        yield scoped
    finally:
        scoped.close()
        if savepoint.is_active:
            savepoint.rollback()
        db.expire_all()
```

- [ ] **Step 4: 跑測試確認通過**

Run: `.venv/bin/pytest tests/integration/test_import_dry_run.py -v`
Expected: 3 passed

- [ ] **Step 5: 跑完整閘門**

Run: `.venv/bin/ruff check app tests && .venv/bin/black --check app tests && .venv/bin/mypy app && .venv/bin/pytest -q`
Expected: 全綠

- [ ] **Step 6: Commit**

```bash
git add app/ingestion/pipeline.py tests/integration/test_import_dry_run.py
git commit -m "feat(import): isolate dry-run writes behind a savepoint

Binding to the outer session's own connection is deliberate: the test suite
shares one DBAPI connection through StaticPool, so opening a second one dies
with 'cannot start a transaction within a transaction'.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: 欄位表單一真相

**Files:**
- Create: `app/ingestion/schema.py`
- Test: `tests/unit/test_import_schema.py`

**Interfaces:**
- Consumes: 無
- Produces:
  - `Kind = Literal["str", "float", "int", "date", "enum", "shares"]`
  - `Column(name, label, kind, required=False, example="", note=None)`
  - `EntitySpec(entity, label, natural_key: tuple[str, ...], columns: tuple[Column, ...])`
  - `SPECS: dict[str, EntitySpec]`，鍵為 `farm` / `customer` / `meter` / `battery` / `contract` / `generation` / `consumption`
  - `EntitySpec.column_names() -> tuple[str, ...]`
  - `EntitySpec.required_names() -> tuple[str, ...]`

- [ ] **Step 1: 寫失敗的測試**

`tests/unit/test_import_schema.py`：

```python
"""欄位表是單一真相：它宣告的欄位必須真的被 importer 讀到。"""

from __future__ import annotations

import inspect

import pytest

from app.ingestion import csv_importer
from app.ingestion.schema import SPECS

# spec 的 entity → csv_importer 裡對應的函式
IMPORTERS = {
    "farm": csv_importer.import_wind_farms,
    "customer": csv_importer.import_customers,
    "meter": csv_importer.import_meters,
    "battery": csv_importer.import_batteries,
    "contract": csv_importer.import_contracts,
    "generation": csv_importer.import_generation,
    "consumption": csv_importer.import_consumption,
}


def test_every_entity_has_an_importer():
    assert set(SPECS) == set(IMPORTERS)


@pytest.mark.parametrize("entity", sorted(SPECS))
def test_declared_columns_are_actually_read(entity):
    """防止 IMPORT_COLS 那種漂移：宣告了卻沒人讀 = 騙使用者。"""
    source = inspect.getsource(IMPORTERS[entity])
    missing = [c.name for c in SPECS[entity].columns if repr(c.name) not in source]
    assert not missing, f"{entity} 宣告了但 importer 沒讀: {missing}"


@pytest.mark.parametrize("entity", sorted(SPECS))
def test_natural_key_columns_are_declared(entity):
    spec = SPECS[entity]
    declared = set(spec.column_names())
    assert set(spec.natural_key) <= declared


@pytest.mark.parametrize("entity", sorted(SPECS))
def test_every_column_has_chinese_label_and_example(entity):
    for col in SPECS[entity].columns:
        assert col.label, f"{entity}.{col.name} 缺中文說明"
        assert col.example, f"{entity}.{col.name} 缺範本示範值"


def test_contract_exposes_the_depth_fields():
    """這四個欄位存在於 importer 卻從沒出現在 UI，是本次要修的問題之一。"""
    names = set(SPECS["contract"].column_names())
    assert {
        "monthly_shares",
        "min_offtake_percent",
        "price_escalation_percent",
        "price_base_year",
    } <= names


def test_farm_exposes_the_engineering_fields():
    names = set(SPECS["farm"].column_names())
    assert {
        "farm_type",
        "capacity_factor_percent",
        "p90_capacity_factor_percent",
        "turbine_count",
        "grid_connection_voltage",
    } <= names
```

- [ ] **Step 2: 跑測試確認它失敗**

Run: `.venv/bin/pytest tests/unit/test_import_schema.py -v`
Expected: FAIL —`ModuleNotFoundError: No module named 'app.ingestion.schema'`

- [ ] **Step 3: 寫實作**

`app/ingestion/schema.py`。逐欄照 `app/ingestion/csv_importer.py` 目前實際讀的鍵抄，一個不漏、不多不少：

```python
"""匯入欄位表：importer、範本、UI 說明與錯誤訊息共用的單一真相。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Kind = Literal["str", "float", "int", "date", "enum", "shares"]


@dataclass(frozen=True)
class Column:
    name: str
    label: str
    kind: Kind
    required: bool = False
    example: str = ""
    note: str | None = None


@dataclass(frozen=True)
class EntitySpec:
    entity: str
    label: str
    natural_key: tuple[str, ...]
    columns: tuple[Column, ...]

    def column_names(self) -> tuple[str, ...]:
        return tuple(c.name for c in self.columns)

    def required_names(self) -> tuple[str, ...]:
        return tuple(c.name for c in self.columns if c.required)

    def column(self, name: str) -> Column | None:
        return next((c for c in self.columns if c.name == name), None)


FARM = EntitySpec(
    entity="farm",
    label="發電案場",
    natural_key=("code",),
    columns=(
        Column("code", "案場代碼", "str", required=True, example="WF-001"),
        Column("name", "案場名稱", "str", required=True, example="彰化外海一期"),
        Column("operator_name", "營運商", "str", example="示範能源"),
        Column("location", "場址", "str", example="彰化縣"),
        Column("installed_capacity_mw", "裝置容量 (MW)", "float", example="100"),
        Column("feed_in_price_per_kwh", "躉售價 (元/度)", "float", example="2.5"),
        Column("commercial_operation_date", "商轉日", "date", example="2024-01-01",
               note="格式 YYYY-MM-DD"),
        Column("status", "狀態", "enum", example="operational",
               note="operational / under_construction / planned"),
        Column("farm_type", "類型", "enum", example="offshore",
               note="offshore（離岸）/ onshore（陸域）/ solar（太陽能）"),
        Column("capacity_factor_percent", "容量因數 P50 (%)", "float", example="45"),
        Column("p90_capacity_factor_percent", "容量因數 P90 (%)", "float",
               example="38"),
        Column("turbine_count", "風機數", "int", example="20"),
        Column("grid_connection_voltage", "並網電壓", "str", example="161kV"),
    ),
)

CUSTOMER = EntitySpec(
    entity="customer",
    label="企業客戶",
    natural_key=("code",),
    columns=(
        Column("code", "客戶代碼", "str", required=True, example="CUS-001"),
        Column("company_name", "公司名稱", "str", required=True, example="示範半導體"),
        Column("industry", "產業", "str", example="半導體"),
        Column("annual_consumption_mwh", "年用電量 (MWh)", "float", example="120000"),
        Column("re_target_percent", "RE 目標 (%)", "float", example="30"),
        Column("target_year", "目標年", "int", example="2030"),
        Column("green_target_type", "綠電目標型態", "enum", example="re_percent",
               note="re_percent（比例）/ energy_mwh（絕對量）"),
        Column("target_energy_mwh", "目標綠電量 (MWh)", "float", example="36000",
               note="green_target_type=energy_mwh 時才有意義"),
    ),
)

METER = EntitySpec(
    entity="meter",
    label="電號／廠區",
    natural_key=("code",),
    columns=(
        Column("customer_code", "所屬客戶代碼", "str", required=True,
               example="CUS-001", note="必須是已存在的客戶"),
        Column("code", "電號", "str", required=True, example="MTR-001"),
        Column("name", "用電名稱", "str", example="一廠"),
        Column("location", "場址", "str", example="新竹科學園區"),
        Column("re_target_percent", "RE 目標 (%)", "float", example="30"),
        Column("annual_consumption_mwh", "年用電量 (MWh)", "float", example="60000"),
    ),
)

BATTERY = EntitySpec(
    entity="battery",
    label="客戶側儲能",
    natural_key=("code",),
    columns=(
        Column("customer_code", "所屬客戶代碼", "str", required=True,
               example="CUS-001", note="必須是已存在的客戶"),
        Column("code", "電池代碼", "str", required=True, example="BAT-001"),
        Column("name", "電池名稱", "str", example="一廠儲能"),
        Column("energy_capacity_mwh", "電量容量 (MWh)", "float", example="20"),
        Column("power_mw", "功率 (MW)", "float", example="5"),
        Column("round_trip_efficiency_percent", "往返效率 (%)", "float",
               example="88"),
        Column("initial_soc_percent", "初始 SOC (%)", "float", example="0"),
    ),
)

CONTRACT = EntitySpec(
    entity="contract",
    label="綠電合約",
    natural_key=("contract_number",),
    columns=(
        Column("contract_number", "合約編號", "str", required=True,
               example="PPA-2026-001"),
        Column("wind_farm_code", "案場代碼", "str", required=True, example="WF-001",
               note="必須是已存在的案場"),
        Column("customer_code", "客戶代碼", "str", required=True, example="CUS-001",
               note="必須是已存在的客戶"),
        Column("start_date", "起始日", "date", example="2026-01-01",
               note="格式 YYYY-MM-DD"),
        Column("end_date", "結束日", "date", example="2035-12-31",
               note="格式 YYYY-MM-DD"),
        Column("contracted_energy_mwh", "年度合約量 (MWh)", "float",
               example="50000"),
        Column("contracted_percentage", "案場發電比例 (%)", "float", example="40"),
        Column("price_per_kwh", "售電價 (元/度)", "float", example="4.2"),
        Column("priority", "優先序", "int", example="100",
               note="數字小者優先分配"),
        Column("status", "狀態", "enum", example="active",
               note="active / pending / expired / terminated"),
        Column("monthly_shares", "月別配比", "shares",
               example="1.35;1.25;1.05;0.85;0.7;0.6;0.6;0.65;0.9;1.15;1.4;1.5",
               note="12 個以分號隔開的相對權重，空白＝平均分攤；不必加總為 1"),
        Column("min_offtake_percent", "保證量下限 (%)", "float", example="80",
               note="take-or-pay：未達此比例仍須付費"),
        Column("price_escalation_percent", "價格年漲幅 (%)", "float", example="2"),
        Column("price_base_year", "價格基準年", "int", example="2026"),
    ),
)

GENERATION = EntitySpec(
    entity="generation",
    label="發電數據",
    natural_key=("wind_farm_code", "period_start", "period_end"),
    columns=(
        Column("wind_farm_code", "案場代碼", "str", required=True, example="WF-001",
               note="必須是已存在的案場"),
        Column("period_start", "區間起", "date", required=True,
               example="2026-01-01", note="格式 YYYY-MM-DD"),
        Column("period_end", "區間迄", "date", required=True, example="2026-01-31",
               note="格式 YYYY-MM-DD"),
        Column("generated_energy_mwh", "發電量 (MWh)", "float", required=True,
               example="12000"),
        Column("data_source", "資料來源", "str", example="mock"),
    ),
)

CONSUMPTION = EntitySpec(
    entity="consumption",
    label="用電數據",
    natural_key=("customer_code", "period_start", "period_end"),
    columns=(
        Column("customer_code", "客戶代碼", "str", required=True, example="CUS-001",
               note="必須是已存在的客戶"),
        Column("period_start", "區間起", "date", required=True,
               example="2026-01-01", note="格式 YYYY-MM-DD"),
        Column("period_end", "區間迄", "date", required=True, example="2026-01-31",
               note="格式 YYYY-MM-DD"),
        Column("consumed_energy_mwh", "用電量 (MWh)", "float", required=True,
               example="10000"),
        Column("data_source", "資料來源", "str", example="mock"),
    ),
)

SPECS: dict[str, EntitySpec] = {
    s.entity: s
    for s in (FARM, CUSTOMER, METER, BATTERY, CONTRACT, GENERATION, CONSUMPTION)
}
```

- [ ] **Step 4: 跑測試**

Run: `.venv/bin/pytest tests/unit/test_import_schema.py -v`
Expected: 全部通過。

若 `test_declared_columns_are_actually_read` 失敗，代表 spec 宣告了 importer 沒讀的欄位——**修 spec，不要放寬測試**。唯一的例外是 `generation` / `consumption` 的 `wind_farm_code` / `customer_code`：它們在 importer 裡確實被讀，但 `natural_key` 用的是 code 而 DB 存的是 id，這個差異在 Task 4 的 `locate()` 處理。

- [ ] **Step 5: 跑完整閘門**

Run: `.venv/bin/ruff check app tests && .venv/bin/black --check app tests && .venv/bin/mypy app && .venv/bin/pytest -q`

- [ ] **Step 6: Commit**

```bash
git add app/ingestion/schema.py tests/unit/test_import_schema.py
git commit -m "feat(import): declare the column spec as a single source of truth

The front-end and the importer each hand-wrote a column list, and the
front-end's had already drifted — it never mentioned the four contract depth
fields. A drift test now makes that impossible.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: 範本產生與 schema／範本端點

前端還沒接，但端點與產生器可以獨立測完。

**Files:**
- Create: `app/ingestion/template.py`, `app/api/v1/imports.py`
- Modify: `app/api/v1/router.py`
- Test: `tests/integration/test_import_template_api.py`

**Interfaces:**
- Consumes: `app.ingestion.schema.SPECS`, `EntitySpec`
- Produces:
  - `template.build_csv(spec: EntitySpec) -> bytes`（含 UTF-8 BOM）
  - `GET /api/v1/import/schema` → `{"entities": [{"entity","label","natural_key",
    "columns":[{"name","label","kind","required","example","note"}]}]}`
  - `GET /api/v1/import/template/{entity}` → `text/csv`，
    `Content-Disposition: attachment; filename="{entity}_template.csv"`

- [ ] **Step 1: 寫失敗的測試**

`tests/integration/test_import_template_api.py`：

```python
"""範本與欄位表端點。範本必須是「下載下來原封不動就能匯回去」的合法輸入。"""

from __future__ import annotations

import csv
import io

from app.ingestion.schema import SPECS


def test_schema_endpoint_lists_every_entity(client):
    resp = client.get("/api/v1/import/schema")
    assert resp.status_code == 200
    entities = {e["entity"] for e in resp.json()["entities"]}
    assert entities == set(SPECS)


def test_schema_endpoint_exposes_labels_and_notes(client):
    body = client.get("/api/v1/import/schema").json()
    contract = next(e for e in body["entities"] if e["entity"] == "contract")
    shares = next(c for c in contract["columns"] if c["name"] == "monthly_shares")
    assert shares["label"] == "月別配比"
    assert shares["note"] and "分號" in shares["note"]


def test_schema_endpoint_needs_no_write_token(client, monkeypatch):
    """欄位定義不含任何資料，不該被寫入閘擋住。"""
    from app.core.config import settings

    monkeypatch.setattr(settings, "admin_write_token", "secret")
    assert client.get("/api/v1/import/schema").status_code == 200


def test_template_has_bom_so_excel_reads_chinese(client):
    resp = client.get("/api/v1/import/template/farm")
    assert resp.status_code == 200
    assert resp.content.startswith(b"\xef\xbb\xbf"), "缺 BOM，Excel 開中文會亂碼"
    assert "attachment" in resp.headers["content-disposition"]
    assert "farm_template.csv" in resp.headers["content-disposition"]


def test_template_header_matches_the_spec(client):
    resp = client.get("/api/v1/import/template/customer")
    rows = list(csv.reader(io.StringIO(resp.content.decode("utf-8-sig"))))
    assert tuple(rows[0]) == SPECS["customer"].column_names()
    assert len(rows) == 2, "範本應為標題列＋一列示範值"


def test_unknown_entity_is_404(client):
    assert client.get("/api/v1/import/template/nope").status_code == 404


def test_downloaded_template_imports_straight_back(client):
    """範本永遠是合法輸入。用沒有外鍵的兩類驗（farm / customer）。"""
    for entity, path in [("farm", "wind-farms"), ("customer", "customers")]:
        content = client.get(f"/api/v1/import/template/{entity}").content
        resp = client.post(
            f"/api/v1/{path}/import",
            files={"file": (f"{entity}.csv", content, "text/csv")},
        )
        assert resp.status_code == 200, entity
        body = resp.json()
        assert body["imported"] == 1, f"{entity} 範本匯不回去: {body}"
        assert body["errors"] == [], f"{entity} 範本自帶錯誤: {body['errors']}"
```

- [ ] **Step 2: 跑測試確認它失敗**

Run: `.venv/bin/pytest tests/integration/test_import_template_api.py -v`
Expected: FAIL —404，路由還不存在。

- [ ] **Step 3: 寫範本產生器**

`app/ingestion/template.py`：

```python
"""由欄位表產生 CSV 範本。"""

from __future__ import annotations

import csv
import io

from app.ingestion.schema import EntitySpec

# Excel 需要 BOM 才會把 UTF-8 中文正確解讀；parse_csv() 用 utf-8-sig 解碼，
# 所以下載下來的範本可以原封不動匯回去。
_BOM = b"\xef\xbb\xbf"


def build_csv(spec: EntitySpec) -> bytes:
    buf = io.StringIO(newline="")
    writer = csv.writer(buf, lineterminator="\r\n")
    writer.writerow(spec.column_names())
    writer.writerow([c.example for c in spec.columns])
    return _BOM + buf.getvalue().encode("utf-8")
```

- [ ] **Step 4: 寫端點**

`app/api/v1/imports.py`：

```python
"""跨實體的匯入輔助端點：欄位表與範本下載。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel

from app.ingestion import template
from app.ingestion.schema import SPECS

router = APIRouter(prefix="/import", tags=["import"])


class ColumnOut(BaseModel):
    name: str
    label: str
    kind: str
    required: bool
    example: str
    note: str | None = None


class EntityOut(BaseModel):
    entity: str
    label: str
    natural_key: list[str]
    columns: list[ColumnOut]


class SchemaOut(BaseModel):
    entities: list[EntityOut]


@router.get("/schema", response_model=SchemaOut)
def import_schema() -> SchemaOut:
    """欄位定義，供前端畫欄位說明。不含任何資料，因此不需要寫入權限。"""
    return SchemaOut(
        entities=[
            EntityOut(
                entity=spec.entity,
                label=spec.label,
                natural_key=list(spec.natural_key),
                columns=[
                    ColumnOut(
                        name=c.name,
                        label=c.label,
                        kind=c.kind,
                        required=c.required,
                        example=c.example,
                        note=c.note,
                    )
                    for c in spec.columns
                ],
            )
            for spec in SPECS.values()
        ]
    )


@router.get("/template/{entity}")
def import_template(entity: str) -> Response:
    spec = SPECS.get(entity)
    if spec is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"未知的匯入類別「{entity}」。",
        )
    return Response(
        content=template.build_csv(spec),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{entity}_template.csv"'
        },
    )
```

`app/api/v1/router.py`：在 import 清單加入 `imports`，並在 `trecs` 之後加一行

```python
api_router.include_router(imports.router)
```

- [ ] **Step 5: 跑測試**

Run: `.venv/bin/pytest tests/integration/test_import_template_api.py -v`
Expected: 7 passed

若 `test_downloaded_template_imports_straight_back` 失敗，代表某個 `example` 值不是合法輸入——**修 `schema.py` 的 example，不要放寬測試**。範本是使用者的起點，它自己匯不回去就沒有意義。

- [ ] **Step 6: 跑完整閘門並 commit**

```bash
.venv/bin/ruff check app tests && .venv/bin/black --check app tests && \
  .venv/bin/mypy app && .venv/bin/pytest -q
git add app/ingestion/template.py app/api/v1/imports.py app/api/v1/router.py \
        tests/integration/test_import_template_api.py
git commit -m "feat(import): serve the column schema and downloadable templates

Templates carry a UTF-8 BOM so Excel renders the Chinese headers instead of
mojibake, and parse_csv already decodes utf-8-sig, so a downloaded template
imports straight back.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: 共用管線、結構化結果與 upsert

這是最大的一個 task，也是唯一動到既有寫入行為的一個。**先確認既有測試全綠再開始。**

**Files:**
- Modify: `app/schemas/common.py`, `app/ingestion/parsing.py`,
  `app/ingestion/pipeline.py`, `app/ingestion/csv_importer.py`
- Test: `tests/integration/test_import_upsert.py`,
  `tests/unit/test_import_errors.py`

**Interfaces:**
- Consumes: `dry_run_session`（Task 1）、`SPECS` / `EntitySpec` / `Column`（Task 2）
- Produces:
  - `app.schemas.common.RowResult`、`ErrorGroup`、擴充後的 `ImportResult`
  - `app.ingestion.parsing.CellError(field: str, label: str, value: str, reason: str)`
  - `app.ingestion.pipeline.run_import(db, spec, rows, handler, *, dry_run=False) -> ImportResult`
  - `app.ingestion.pipeline.Handler` protocol：
    `preload(db) -> dict`、`build(row, ctx) -> dict`、`locate(db, row, ctx) -> object | None`、
    `create(db, payload) -> None`、`update(db, existing, payload) -> list[str]`

- [ ] **Step 1: 先確認起點是綠的**

Run: `.venv/bin/pytest -q`
Expected: 全綠。若不是，先停下來修好再繼續。

- [ ] **Step 2: 寫結果 schema**

`app/schemas/common.py` 追加（`ImportResult` 既有三個欄位一字不改）：

```python
from typing import Literal


class RowResult(BaseModel):
    """單列的處理結果。row 是 CSV 行號：標題列 = 1，資料首列 = 2。"""

    row: int
    action: Literal["create", "update", "skip", "error"]
    key: str | None = None
    changed: list[str] = []
    message: str | None = None


class ErrorGroup(BaseModel):
    """同一欄、同一種原因的錯誤收斂成一組。

    分組而非截斷：使用者要的不是兩千則一樣的訊息，而是「這一欄整欄格式錯了」。
    """

    field: str | None = None
    message: str
    count: int
    sample_rows: list[int] = []
    sample_value: str | None = None


class ImportResult(BaseModel):
    """Result of a CSV / bulk import operation."""

    imported: int
    skipped: int = 0
    errors: list[str] = []
    updated: int = 0
    error_groups: list[ErrorGroup] = []
    sample_rows: list[RowResult] = []
    total_rows: int = 0
    dry_run: bool = False
```

- [ ] **Step 3: 寫錯誤訊息的測試**

`tests/unit/test_import_errors.py`：

```python
"""解析錯誤必須指得出欄位、原值，並且是中文。"""

from __future__ import annotations

import pytest

from app.ingestion import parsing as p
from app.ingestion.schema import SPECS


def test_bad_float_names_the_column_in_chinese():
    col = SPECS["farm"].column("installed_capacity_mw")
    with pytest.raises(p.CellError) as exc:
        p.parse_cell(col, "abc")
    err = exc.value
    assert err.field == "installed_capacity_mw"
    assert err.value == "abc"
    assert "裝置容量" in err.reason
    assert "不是數字" in err.reason


def test_bad_date_says_the_expected_format():
    col = SPECS["contract"].column("start_date")
    with pytest.raises(p.CellError) as exc:
        p.parse_cell(col, "03/07/2026")
    assert "YYYY-MM-DD" in exc.value.reason


def test_blank_optional_cell_is_none():
    col = SPECS["farm"].column("turbine_count")
    assert p.parse_cell(col, "   ") is None


def test_blank_required_cell_is_an_error():
    col = SPECS["farm"].column("code")
    with pytest.raises(p.CellError) as exc:
        p.parse_cell(col, "")
    assert "必填" in exc.value.reason


def test_shares_parses_semicolon_weights():
    col = SPECS["contract"].column("monthly_shares")
    assert p.parse_cell(col, "1;2;3") == [1.0, 2.0, 3.0]
```

- [ ] **Step 4: 跑測試確認失敗**

Run: `.venv/bin/pytest tests/unit/test_import_errors.py -v`
Expected: FAIL —`AttributeError: module 'app.ingestion.parsing' has no attribute 'CellError'`

- [ ] **Step 5: 擴充 parsing**

`app/ingestion/parsing.py` 追加（`s` / `f` / `i` / `d` 原樣保留，仍有其他呼叫者）：

```python
from app.ingestion.schema import Column


class CellError(Exception):
    """單一儲存格解析失敗，帶得走欄位與原值。"""

    def __init__(self, field: str, label: str, value: str, reason: str) -> None:
        super().__init__(reason)
        self.field = field
        self.label = label
        self.value = value
        self.reason = reason


def parse_cell(column: Column, raw: str | None) -> object:
    """依欄位型別解析，失敗時丟出帶中文原因的 CellError。"""
    text = s(raw)
    if text is None:
        if column.required:
            raise CellError(column.name, column.label, "",
                            f"{column.label}為必填，不可空白")
        return None
    try:
        if column.kind == "float":
            return float(text)
        if column.kind == "int":
            return int(text)
        if column.kind == "date":
            return d(text)
        if column.kind == "shares":
            return [float(x) for x in text.split(";")]
        return text
    except CellError:
        raise
    except ValueError as exc:
        raise CellError(
            column.name, column.label, text, _reason(column, text)
        ) from exc


def _reason(column: Column, text: str) -> str:
    if column.kind in ("float", "int"):
        return f"{column.label}「{text}」不是數字"
    if column.kind == "date":
        return f"{column.label}「{text}」不是有效日期，格式須為 YYYY-MM-DD"
    if column.kind == "shares":
        return f"{column.label}「{text}」格式錯誤，須為以分號隔開的數字"
    return f"{column.label}「{text}」無效"
```

注意 `d()` 對壞日期丟的是 `ValueError`（`datetime.strptime` 的行為），會被上面接住。

- [ ] **Step 6: 跑測試確認通過**

Run: `.venv/bin/pytest tests/unit/test_import_errors.py -v`
Expected: 5 passed

- [ ] **Step 7: 寫 upsert 的測試**

`tests/integration/test_import_upsert.py`：

```python
"""upsert 語意：重複匯入是更新或 no-op，不是靜默略過，也不是複製一份。"""

from __future__ import annotations

from app.ingestion import csv_importer
from app.models import Customer, GenerationData, WindFarm

FARM_CSV = """code,name,installed_capacity_mw
WF-U1,原始名稱,100
"""

FARM_CSV_RENAMED = """code,name,installed_capacity_mw
WF-U1,改過的名稱,100
"""

FARM_CSV_BLANK_NAME = """code,name,installed_capacity_mw
WF-U1,,120
"""


def _rows(text):
    return csv_importer.parse_csv(text)


def test_second_identical_import_is_a_noop_skip(db):
    first = csv_importer.import_wind_farms(db, _rows(FARM_CSV))
    assert (first.imported, first.updated, first.skipped) == (1, 0, 0)

    second = csv_importer.import_wind_farms(db, _rows(FARM_CSV))
    assert (second.imported, second.updated, second.skipped) == (0, 0, 1)
    assert db.query(WindFarm).count() == 1


def test_changed_value_becomes_an_update(db):
    csv_importer.import_wind_farms(db, _rows(FARM_CSV))
    result = csv_importer.import_wind_farms(db, _rows(FARM_CSV_RENAMED))

    assert (result.imported, result.updated, result.skipped) == (0, 1, 0)
    assert result.sample_rows[0].action == "update"
    assert result.sample_rows[0].changed == ["name"]
    assert db.query(WindFarm).one().name == "改過的名稱"


def test_blank_cell_does_not_wipe_an_existing_value(db):
    """Excel 導出常整欄空白，空白＝不動，不是清空。"""
    csv_importer.import_wind_farms(db, _rows(FARM_CSV))
    csv_importer.import_wind_farms(db, _rows(FARM_CSV_BLANK_NAME))

    farm = db.query(WindFarm).one()
    assert farm.name == "原始名稱"
    assert farm.installed_capacity_mw == 120


def test_generation_reimport_does_not_double_the_data(db):
    """匯兩次變兩倍會直接汙染結算金額。"""
    db.add(WindFarm(code="WF-G1", name="G1", installed_capacity_mw=10))
    db.commit()
    gen_csv = """wind_farm_code,period_start,period_end,generated_energy_mwh
WF-G1,2026-01-01,2026-01-31,1000
"""
    csv_importer.import_generation(db, _rows(gen_csv))
    csv_importer.import_generation(db, _rows(gen_csv))

    rows = db.query(GenerationData).all()
    assert len(rows) == 1
    assert rows[0].generated_energy_mwh == 1000


def test_dry_run_matches_the_real_import(db):
    """選後端 dry-run 的整個理由：預覽說什麼，按下去就是什麼。"""
    csv = """code,company_name,annual_consumption_mwh
CUS-D1,甲公司,100
CUS-D2,乙公司,not-a-number
"""
    preview = csv_importer.import_customers(db, _rows(csv), dry_run=True)
    assert db.query(Customer).count() == 0

    real = csv_importer.import_customers(db, _rows(csv))
    assert (preview.imported, preview.updated, preview.skipped) == (
        real.imported, real.updated, real.skipped
    )
    assert [g.message for g in preview.error_groups] == [
        g.message for g in real.error_groups
    ]
    assert preview.dry_run is True and real.dry_run is False
```

- [ ] **Step 8: 跑測試確認失敗**

Run: `.venv/bin/pytest tests/integration/test_import_upsert.py -v`
Expected: FAIL —`import_wind_farms()` 還沒有 `dry_run` 參數、`ImportResult` 還沒有 `updated`。

- [ ] **Step 9: 寫共用管線**

`app/ingestion/pipeline.py` 追加：

```python
from collections import OrderedDict
from collections.abc import Iterable
from typing import Any, Protocol

from app.core.exceptions import DomainError
from app.ingestion.parsing import CellError
from app.ingestion.schema import EntitySpec
from app.schemas.common import ErrorGroup, ImportResult, RowResult

# 成功列只回樣本：確認欄位有對上不需要看一萬列。
_SAMPLE_LIMIT = 20
# 每組錯誤附幾個列號，讓使用者找得到但不洗版。
_GROUP_ROWS = 10


class Handler(Protocol):
    def preload(self, db: Any) -> dict[str, Any]: ...
    def build(self, row: dict[str, str], ctx: dict[str, Any]) -> dict[str, Any]: ...
    def locate(
        self, db: Any, row: dict[str, str], ctx: dict[str, Any]
    ) -> Any | None: ...
    def create(self, db: Any, payload: dict[str, Any]) -> None: ...
    def update(self, db: Any, existing: Any, payload: dict[str, Any]) -> list[str]: ...


def _key_of(spec: EntitySpec, row: dict[str, str]) -> str:
    return "/".join((row.get(c) or "").strip() for c in spec.natural_key)


def _group(errors: list[tuple[int, str | None, str, str | None]]) -> list[ErrorGroup]:
    """依 (欄位, 原因) 收斂。payload 大小由錯誤的種類數決定，不由列數決定。"""
    buckets: OrderedDict[tuple[str | None, str], ErrorGroup] = OrderedDict()
    for row_no, field, reason, value in errors:
        key = (field, reason)
        group = buckets.get(key)
        if group is None:
            buckets[key] = ErrorGroup(
                field=field, message=reason, count=1,
                sample_rows=[row_no], sample_value=value,
            )
        else:
            group.count += 1
            if len(group.sample_rows) < _GROUP_ROWS:
                group.sample_rows.append(row_no)
    return list(buckets.values())


def run_import(
    db: Any,
    spec: EntitySpec,
    rows: Iterable[dict[str, str]],
    handler: Handler,
    *,
    dry_run: bool = False,
) -> ImportResult:
    """逐列跑匯入。dry_run 時走完全相同的路徑，只是最後整個退回。"""
    if dry_run:
        with dry_run_session(db) as scoped:
            result = _run(scoped, spec, rows, handler)
        result.dry_run = True
        return result
    return _run(db, spec, rows, handler)


def _run(
    db: Any, spec: EntitySpec, rows: Iterable[dict[str, str]], handler: Handler
) -> ImportResult:
    ctx = handler.preload(db)
    created = updated = skipped = 0
    errors: list[tuple[int, str | None, str, str | None]] = []
    samples: list[RowResult] = []
    total = 0

    for row_no, row in enumerate(rows, start=2):
        total += 1
        key = _key_of(spec, row)
        # 每列一個 SAVEPOINT：Postgres 在語句失敗後會讓整個交易進入 aborted
        # 狀態，不退回 savepoint 的話後面每一列都會跟著失敗。
        nested = db.begin_nested()
        try:
            payload = handler.build(row, ctx)
            existing = handler.locate(db, row, ctx)
            if existing is None:
                handler.create(db, payload)
                created += 1
                action, changed = "create", []
            else:
                changed = handler.update(db, existing, payload)
                if changed:
                    updated += 1
                    action = "update"
                else:
                    skipped += 1
                    action = "skip"
            db.commit()
            if len(samples) < _SAMPLE_LIMIT:
                samples.append(
                    RowResult(row=row_no, action=action, key=key or None,
                              changed=changed)
                )
        except CellError as exc:
            if nested.is_active:
                nested.rollback()
            errors.append((row_no, exc.field, exc.reason, exc.value))
        except DomainError as exc:
            if nested.is_active:
                nested.rollback()
            errors.append((row_no, None, str(exc), None))
        except Exception as exc:  # noqa: BLE001 - 逐列回報，不中斷整批
            if nested.is_active:
                nested.rollback()
            errors.append((row_no, None, str(exc), None))

    groups = _group(errors)
    return ImportResult(
        imported=created,
        updated=updated,
        skipped=skipped,
        errors=[f"row {n}: {reason}" for n, _, reason, _ in errors],
        error_groups=groups,
        sample_rows=samples,
        total_rows=total,
    )
```

- [ ] **Step 10: 把七個 importer 改成 handler**

改寫 `app/ingestion/csv_importer.py`。每個 `import_*` 保留原簽章並加上 `dry_run` 關鍵字參數，內部委派給 `run_import`。以案場為例（其餘六個照同一形狀）：

```python
class _FarmHandler:
    spec = schema.FARM

    def preload(self, db: Session) -> dict[str, Any]:
        return {}  # 案場沒有外鍵，不需要預載

    def build(self, row: dict[str, str], ctx: dict[str, Any]) -> dict[str, Any]:
        return {
            c.name: p.parse_cell(c, row.get(c.name))
            for c in self.spec.columns
            if c.name in row
        }

    def locate(
        self, db: Session, row: dict[str, str], ctx: dict[str, Any]
    ) -> WindFarm | None:
        code = p.s(row.get("code"))
        return None if code is None else BaseRepository(WindFarm, db).get_by(code=code)

    def create(self, db: Session, payload: dict[str, Any]) -> None:
        data = WindFarmCreate(
            **{**payload, "status": WindFarmStatus(
                payload.get("status") or WindFarmStatus.OPERATIONAL.value)}
        )
        wind_farm_svc.create(db, data)

    def update(
        self, db: Session, existing: WindFarm, payload: dict[str, Any]
    ) -> list[str]:
        # 空白＝不動：Excel 導出常整欄空白，把它當「清空」會毀掉既有資料。
        changed = [
            name for name, value in payload.items()
            if value is not None and getattr(existing, name, None) != value
        ]
        for name in changed:
            setattr(existing, name, payload[name])
        if changed:
            db.flush()
        return changed


def import_wind_farms(
    db: Session, rows: Iterable[dict], *, dry_run: bool = False
) -> ImportResult:
    return pipeline.run_import(
        db, schema.FARM, rows, _FarmHandler(), dry_run=dry_run
    )
```

`generation` / `consumption` 的 `locate()` 要把 code 轉成 id 再查自然鍵：

```python
    def locate(self, db, row, ctx):
        farm_id = ctx["farms"].get(p.s(row.get("wind_farm_code")))
        if farm_id is None:
            return None
        return (
            db.query(GenerationData)
            .filter_by(
                wind_farm_id=farm_id,
                period_start=p.parse_cell(self.spec.column("period_start"),
                                          row.get("period_start")),
                period_end=p.parse_cell(self.spec.column("period_end"),
                                        row.get("period_end")),
            )
            .first()
        )
```

且 `preload()` 要回傳預載的對照表：

```python
    def preload(self, db: Session) -> dict[str, Any]:
        return {
            "farms": dict(db.execute(select(WindFarm.code, WindFarm.id)).all()),
        }
```

外鍵找不到時，`build()` 要丟 `CellError`，訊息形如
`f"案場代碼「{code}」不存在，請先建立該案場"`。

- [ ] **Step 11: 寫標題列驗證的測試**

缺必填欄是**整檔**的問題，不是一千列各自的問題。一份標題打錯的檔不該產生一千則一樣的訊息。

`tests/integration/test_import_upsert.py` 追加：

```python
def test_missing_required_header_is_one_file_level_error(db):
    """標題列缺必填欄 → 一則整檔錯誤，不是逐列洗版。"""
    csv = "name,installed_capacity_mw\n甲,100\n乙,200\n丙,300\n"
    result = csv_importer.import_wind_farms(db, _rows(csv))

    assert result.imported == 0
    assert len(result.error_groups) == 1
    group = result.error_groups[0]
    assert group.count == 1, "整檔錯誤只該有一則"
    assert group.sample_rows == [1], "指向標題列"
    assert "code" in group.message and "缺少" in group.message


def test_unknown_columns_are_ignored_not_rejected(db):
    """Excel 導出常多欄，多欄不該擋住匯入。"""
    csv = "code,name,installed_capacity_mw,備註,某個空欄\nWF-X1,X1,100,隨便寫,\n"
    result = csv_importer.import_wind_farms(db, _rows(csv))
    assert result.imported == 1
    assert result.error_groups == []
```

- [ ] **Step 12: 跑測試確認失敗，然後實作標題列驗證**

Run: `.venv/bin/pytest tests/integration/test_import_upsert.py -k header -v`
Expected: FAIL — 目前會逐列產生錯誤。

在 `pipeline._run()` 的迴圈**之前**加上：

```python
def _check_header(spec: EntitySpec, rows: list[dict[str, str]]) -> ErrorGroup | None:
    """缺必填欄是整檔的問題。逐列報一千次只會把真正的訊息淹掉。"""
    if not rows:
        return None
    present = set(rows[0])
    missing = [c for c in spec.required_names() if c not in present]
    if not missing:
        return None
    labels = "、".join(
        f"{spec.column(m).label}（{m}）" for m in missing  # type: ignore[union-attr]
    )
    return ErrorGroup(
        field=None,
        message=f"標題列缺少必填欄位：{labels}。請用「下載範本」取得正確的標題列。",
        count=1,
        sample_rows=[1],
    )
```

`_run()` 開頭改為先把 `rows` 收成 list（原本是 Iterable，`_check_header` 需要看第一列），再：

```python
    rows = list(rows)
    header_error = _check_header(spec, rows)
    if header_error is not None:
        return ImportResult(
            imported=0, updated=0, skipped=0,
            errors=[header_error.message],
            error_groups=[header_error],
            total_rows=len(rows),
        )
```

多餘欄位不需要處理——`build()` 只讀 `c.name in row` 的欄位，其餘自然被忽略。

- [ ] **Step 13: 跑測試確認通過**

Run: `.venv/bin/pytest tests/integration/test_import_upsert.py -v`
Expected: 全部通過。

- [ ] **Step 14: 跑全部測試**

Run: `.venv/bin/pytest -q`
Expected: 全綠，**包含未經修改的 `tests/integration/test_taipower_contracts.py`**。
`second.skipped == 8` 在新語意下仍成立：那 8 列既有且無欄位變更，就是 no-op。
若它變紅，是實作錯了，不是測試該改。

- [ ] **Step 15: 跑完整閘門並 commit**

```bash
.venv/bin/ruff check app tests && .venv/bin/black --check app tests && \
  .venv/bin/mypy app && .venv/bin/pytest --cov=app --cov-fail-under=90 -q
git add app/schemas/common.py app/ingestion/ tests/
git commit -m "feat(import): add dry-run, upsert and per-row structured results

Duplicate rows now update instead of being silently swallowed, and a
re-imported generation file no longer doubles the data it describes.
Errors group by (field, reason) so a systematically wrong column reads as one
finding rather than two thousand identical lines.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: 端點接上 dry_run，補齊缺的匯入入口

**Files:**
- Modify: `app/api/v1/wind_farms.py`, `customers.py`, `contracts.py`, `meters.py`,
  `generation.py`, `consumption.py`, `batteries.py`
- Test: `tests/integration/test_import_api.py`

**Interfaces:**
- Consumes: Task 4 的 `import_*(db, rows, *, dry_run=False)`
- Produces: 七個 `POST /api/v1/{entity}/import?dry_run=<bool>`

- [ ] **Step 1: 寫失敗的測試**

`tests/integration/test_import_api.py`：

```python
"""匯入端點：dry_run 參數與補齊的入口。"""

from __future__ import annotations

FARM_CSV = b"code,name,installed_capacity_mw\nWF-A1,A1,100\n"


def _post(client, path, content, **params):
    return client.post(
        path, files={"file": ("in.csv", content, "text/csv")}, params=params
    )


def test_dry_run_reports_without_writing(client):
    resp = _post(client, "/api/v1/wind-farms/import", FARM_CSV, dry_run=True)
    assert resp.status_code == 200
    body = resp.json()
    assert body["imported"] == 1 and body["dry_run"] is True

    assert client.get("/api/v1/wind-farms").json() == []


def test_real_import_writes(client):
    _post(client, "/api/v1/wind-farms/import", FARM_CSV)
    codes = [f["code"] for f in client.get("/api/v1/wind-farms").json()]
    assert codes == ["WF-A1"]


def test_batteries_import_endpoint_exists(client):
    client.post("/api/v1/customers", json={
        "code": "CUS-B1", "company_name": "B1",
        "annual_consumption_mwh": 1.0, "re_target_percent": 10.0,
    })
    csv = b"customer_code,code,name,energy_capacity_mwh,power_mw\nCUS-B1,BAT-1,B,20,5\n"
    resp = _post(client, "/api/v1/batteries/import", csv)
    assert resp.status_code == 200
    assert resp.json()["imported"] == 1


def test_error_groups_collapse_a_systematically_bad_column(client):
    csv = (b"code,name,installed_capacity_mw\n"
           b"WF-E1,E1,abc\nWF-E2,E2,def\nWF-E3,E3,ghi\n")
    body = _post(client, "/api/v1/wind-farms/import", csv, dry_run=True).json()

    assert len(body["error_groups"]) == 1
    group = body["error_groups"][0]
    assert group["field"] == "installed_capacity_mw"
    assert group["count"] == 3
    assert group["sample_rows"] == [2, 3, 4]
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `.venv/bin/pytest tests/integration/test_import_api.py -v`
Expected: FAIL —`dry_run` 被忽略、`/batteries/import` 404。

- [ ] **Step 3: 六個既有端點加 dry_run**

每個檔案的 `/import` 改成（以 `customers.py` 為例，其餘五個同形）：

```python
@router.post("/import", response_model=ImportResult, dependencies=[_write])
async def import_customers(
    file: UploadFile = File(..., description="CSV of customer rows"),
    dry_run: bool = Query(False, description="只驗證與預覽，不寫入"),
    db: Session = Depends(get_db),
) -> ImportResult:
    rows = csv_importer.parse_csv(await read_upload(file))
    return csv_importer.import_customers(db, rows, dry_run=dry_run)
```

`generation.py` / `consumption.py` 已 import 了 `Query`；其餘檔案若沒有，補進 `from fastapi import ... Query ...`。

- [ ] **Step 4: batteries 補 /import**

`app/api/v1/batteries.py` 加在檔案第一個路由之前：

```python
@router.post("/import", response_model=ImportResult, dependencies=[_write])
async def import_batteries(
    file: UploadFile = File(..., description="CSV of battery rows"),
    dry_run: bool = Query(False, description="只驗證與預覽，不寫入"),
    db: Session = Depends(get_db),
) -> ImportResult:
    rows = csv_importer.parse_csv(await read_upload(file))
    return csv_importer.import_batteries(db, rows, dry_run=dry_run)
```

需要補的 import：`File`、`Query`、`UploadFile`、`read_upload`、`csv_importer`、`ImportResult`。

- [ ] **Step 5: 跑測試**

Run: `.venv/bin/pytest tests/integration/test_import_api.py -v`
Expected: 4 passed

- [ ] **Step 6: 跑完整閘門並 commit**

```bash
.venv/bin/ruff check app tests && .venv/bin/black --check app tests && \
  .venv/bin/mypy app && .venv/bin/pytest -q
git add app/api/v1/ tests/integration/test_import_api.py
git commit -m "feat(api): accept dry_run on every import and expose battery import

import_batteries had existed since storage shipped but was reachable only
from the test seeder.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: 前端預覽面板

**Files:**
- Modify: `web/api.js`, `web/app.js:2572-2619`, `web/styles.css`
- Test: `tests/integration/test_spa_static.py`（加一條冒煙測試）

**Interfaces:**
- Consumes: `GET /import/schema`、`GET /import/template/{entity}`、
  `POST /{entity}/import?dry_run=`
- Produces: 無（終端消費者）

- [ ] **Step 1: api.js 支援 dry_run 與新實體**

`upload()` 改為接受查詢參數，並補齊實體：

```javascript
  function upload(path, file, params) {
    var fd = new FormData();
    fd.append("file", file);
    var qs = params && params.dry_run ? "?dry_run=true" : "";
    var headers = { Accept: "application/json" };
    if (adminToken) headers["X-Admin-Token"] = adminToken;
    return fetch(V1 + path + qs, { method: "POST", headers: headers, body: fd })
      .then(function (resp) {
        return resp.text().then(function (body) {
          if (!resp.ok) {
            var detail = body;
            try { detail = JSON.parse(body).detail || body; } catch (e) { /* keep */ }
            throw new ApiError(resp.status + ": " + detail, resp.status);
          }
          return body ? JSON.parse(body) : null;
        });
      })
      .catch(function (err) {
        if (err instanceof ApiError) throw err;
        throw new ApiError("無法連線到後端 API：" + err.message, 0);
      });
  }
```

`global.api` 內：把六個 `importXxx` 改為 `function (file, opts) { return upload("/xxx/import", file, opts); }`，並新增

```javascript
    importGeneration: function (file, o) { return upload("/generation/import", file, o); },
    importConsumption: function (file, o) { return upload("/consumption/import", file, o); },
    importBatteries: function (file, o) { return upload("/batteries/import", file, o); },
    importSchema: function () { return get("/import/schema"); },
    importTemplateUrl: function (entity) { return V1 + "/import/template/" + entity; },
```

- [ ] **Step 2: app.js 換掉 IMPORT_COLS 與匯入 modal**

刪除 `IMPORT_COLS`（`web/app.js:2573-2578`），改為啟動時抓一次並快取：

```javascript
  var IMPORT_SCHEMA = null;
  function loadImportSchema() {
    if (IMPORT_SCHEMA) return Promise.resolve(IMPORT_SCHEMA);
    return api.importSchema().then(function (r) {
      IMPORT_SCHEMA = {};
      r.entities.forEach(function (e) { IMPORT_SCHEMA[e.entity] = e; });
      return IMPORT_SCHEMA;
    });
  }
```

`IMPORT_FN` 補齊七個實體，並改為接受 `opts`：

```javascript
  var IMPORT_FN = {
    farm: function (f, o) { return api.importFarms(f, o); },
    customer: function (f, o) { return api.importCustomers(f, o); },
    contract: function (f, o) { return api.importContracts(f, o); },
    meter: function (f, o) { return api.importMeters(f, o); },
    battery: function (f, o) { return api.importBatteries(f, o); },
    generation: function (f, o) { return api.importGeneration(f, o); },
    consumption: function (f, o) { return api.importConsumption(f, o); },
  };
```

`openImportModal(kind)` 重寫為兩段式：

1. 開窗時 `loadImportSchema()`，畫出欄位表格（欄名、中文說明、必填標記、備註）與「下載範本」連結（`api.importTemplateUrl(kind)`）
2. `input[type=file]` 的 `change` 事件即自動送 `IMPORT_FN[kind](file, {dry_run: true})`，把結果畫成預覽：
   - 三個數字：`新增 r.imported`／`更新 r.updated`／`錯誤 Σ r.error_groups[].count`
   - 錯誤分組清單：每組一行「`欄位中文名` · `message`（`count` 列，例：第 `sample_rows.join("、")` 列，值「`sample_value`」）」
   - 成功樣本表：`r.sample_rows` 逐列列出 `row` / `key` / 動作徽章 / `changed.join("、")`
3. 「確認匯入」按鈕：有錯誤時文字為 `確認匯入（將略過 N 列）`，點擊送 `{dry_run: false}`，成功後 `route()` 重繪

**必須一併刪除**：
- `setTimeout(close, ...)`（`web/app.js:2615`）——錯誤還沒讀完就關窗
- `r.errors.slice(0, 5)`（`web/app.js:2612`）——改用完整的 `error_groups`
- `var editMode = true`（`web/app.js:2477`）與三處 `if (!editMode) return ""`
  （`:2568`、`:2586`、`:2621`）——這個旗標從未被改寫，是死碼

- [ ] **Step 3: styles.css 加預覽面板樣式**

沿用既有 token（`--bad` / `--ok` / `--muted` / `--panel` / `--line2`），新增：

```css
.imp-sum{display:flex;gap:14px;margin:10px 0}
.imp-sum b{font-size:18px}
.imp-grp{border-left:3px solid var(--bad);background:var(--panel);padding:7px 10px;
  margin:6px 0;font-size:12px;border-radius:0 6px 6px 0}
.imp-rows{max-height:260px;overflow:auto;font-size:11.5px}
.imp-act{display:inline-block;padding:0 6px;border-radius:5px;font-size:10.5px;
  font-weight:700}
.imp-act.create{background:var(--ok-soft);color:var(--ok)}
.imp-act.update{background:var(--warn-soft);color:var(--warn)}
.imp-act.skip{background:var(--panel2);color:var(--faint)}
```

若 `--ok-soft` / `--warn-soft` / `--warn` 在 `:root` 未定義，先在 `:root` 與深色主題各補一組，兩個主題都要有——對比不足是既有 backlog 上的問題，不要新增一筆。

- [ ] **Step 4: 加 SPA 冒煙測試**

`tests/integration/test_spa_static.py` 追加：

```python
def test_import_schema_and_template_are_served(client):
    assert client.get("/api/v1/import/schema").status_code == 200
    assert client.get("/api/v1/import/template/contract").status_code == 200
```

- [ ] **Step 5: 用真瀏覽器驗證**

合成的 `MouseEvent` 不做命中測試，抓不到被遮住的元素——一定要用真實座標點擊。

```bash
.venv/bin/uvicorn app.main:app --port 8010 &
```

用 Playwright 開 `http://localhost:8010/app/#/farms`，實際點「⇪ 匯入 CSV」、選一個含壞列的檔案，截圖確認：
1. 欄位說明列出合約深化欄位（切到合約頁時）
2. 選檔後**沒有按任何按鈕**就出現預覽
3. 錯誤分組顯示中文、列號正確
4. 面板**不會自動關閉**
5. 按「確認匯入」後資料真的進去

- [ ] **Step 6: 跑完整閘門並 commit**

```bash
.venv/bin/ruff check app tests && .venv/bin/black --check app tests && \
  .venv/bin/mypy app && .venv/bin/pytest --cov=app --cov-fail-under=90 -q
git add web/ tests/integration/test_spa_static.py
git commit -m "feat(web): preview a CSV import before it writes anything

Picking a file now shows what would happen — created, updated, skipped, and
every error grouped by column — instead of writing first and showing five
truncated English messages that vanish after four seconds.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Postgres 驗證與文件

spec 裡唯一還沒被證明的假設是 Postgres 的逐列 SAVEPOINT。**沒跑過這一步，不要宣稱這個功能完成。**

**Files:**
- Modify: `README.md`, `CHANGELOG.md`, `docs/PRD.md`

- [ ] **Step 1: 起一個真的 Postgres**

這台機器沒有 Docker，Homebrew 也太舊（Intel 路徑、不認得 macOS 26）。改用 `pgserver`——它自帶 PostgreSQL binaries，不需要系統安裝或 sudo。已在 worktree 的 venv 裝好並驗過 SAVEPOINT 語意；**不寫進 `pyproject.toml`**，它只是驗證工具。

```bash
.venv/bin/python - <<'PY'
import pathlib, pgserver
d = pathlib.Path(".pgtest/pgdata").absolute()
d.parent.mkdir(exist_ok=True)
srv = pgserver.get_server(d)
print(srv.get_uri())
PY
```

把印出的 URI 轉成 SQLAlchemy 的形式（`postgresql://` → `postgresql+psycopg://`）設進 `DATABASE_URL`，然後：

```bash
.venv/bin/alembic upgrade head
```

`.pgtest/` 用完即刪，不要提交。

若 `pgserver` 這條也不通，改用 Neon 的測試分支；**不要跳過這一步**。

- [ ] **Step 2: 實跑一個含壞列的匯入**

```bash
.venv/bin/uvicorn app.main:app --port 8011 &
printf 'code,name,installed_capacity_mw\nWF-P1,好的,100\nWF-P2,壞的,abc\nWF-P3,也好的,120\n' > /tmp/pg.csv
curl -s -F file=@/tmp/pg.csv "http://localhost:8011/api/v1/wind-farms/import?dry_run=true"
curl -s -F file=@/tmp/pg.csv "http://localhost:8011/api/v1/wind-farms/import"
curl -s "http://localhost:8011/api/v1/wind-farms" | grep -c WF-P
```

Expected：兩次呼叫的 `imported` 都是 2、`error_groups[0].count` 都是 1；最後查得到 `WF-P1` 與 `WF-P3`。

**若 Postgres 在壞列之後把後續列一起判失敗**，代表逐列 SAVEPOINT 沒生效——回到 Task 4 Step 9 的 `_run()` 修正，不要繼續往下。

- [ ] **Step 3: 更新文件**

- `README.md`：匯入章節補上範本下載與預覽的說明，附一張預覽面板截圖
- `CHANGELOG.md` 的 `[Unreleased]`：加 Added（範本下載、匯入預覽、逐列錯誤分組、battery/generation/consumption 匯入入口）與 Fixed（重複匯入發電資料會加倍）
- `docs/PRD.md`：EPIC-1.2 的 (c) 標為完成，(a)(b) 維持待辦

- [ ] **Step 4: Commit**

```bash
git add README.md CHANGELOG.md docs/PRD.md
git commit -m "docs: record the CSV import preview and template download

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## 完成判準

- [ ] `.venv/bin/pytest --cov=app --cov-fail-under=90` 綠
- [ ] `ruff` / `black --check` / `mypy app` 全綠
- [ ] `tests/integration/test_taipower_contracts.py` **未經修改**仍綠
- [ ] Postgres 上實跑過含壞列的匯入（Task 7 Step 2）
- [ ] 真瀏覽器點過一次完整流程（Task 6 Step 5）
- [ ] 合約匯入的欄位說明看得到四個深化欄位
