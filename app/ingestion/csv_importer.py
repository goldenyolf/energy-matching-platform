"""CSV import: parse CSV content into domain rows and upsert them.

Each importer's write logic is a small ``Handler`` (see ``app.ingestion.pipeline``)
that plugs into the shared pipeline: one SAVEPOINT per row, natural-key upsert
(create / update / no-op skip), and grouped, Chinese error messages. Handlers
declare *what* to read and *how* to find/write a row; the loop, the dry-run
isolation, and the result shape all live in the pipeline.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable
from dataclasses import replace
from typing import Any

from pydantic import BaseModel
from sqlalchemy import inspect as sa_inspect
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ingestion import parsing as p
from app.ingestion import pipeline, schema
from app.ingestion.parsing import CellError
from app.ingestion.schema import Column, EntitySpec
from app.models import (
    Battery,
    ConsumptionData,
    Contract,
    Customer,
    GenerationData,
    Meter,
    WindFarm,
)
from app.repositories.base import BaseRepository
from app.schemas.battery import BatteryCreate
from app.schemas.common import ImportResult
from app.schemas.consumption import ConsumptionCreate
from app.schemas.contract import ContractCreate
from app.schemas.customer import CustomerCreate
from app.schemas.generation import GenerationCreate
from app.schemas.meter import MeterCreate
from app.schemas.wind_farm import WindFarmCreate
from app.services import contracts as contract_svc
from app.services import customers as customer_svc
from app.services import measurements as measurement_svc
from app.services import meter_service
from app.services import wind_farms as wind_farm_svc
from app.services.battery_service import create as create_battery


class _Rows(list[dict[str, str]]):
    """跟一般 list 沒有兩樣，只是多帶著 CSV 標題列。

    這樣即使資料列是 0 筆（例如標題打錯、DictReader 因此一列都讀不出來），
    ``pipeline._check_header`` 仍看得到實際的標題，不會把「整份標題都是錯的」
    誤判成「檔案是空的所以沒問題」。
    """

    fieldnames: tuple[str, ...] = ()


def parse_csv(content: str | bytes) -> list[dict[str, str]]:
    """Parse CSV text (or bytes) into a list of row dicts."""
    if isinstance(content, bytes):
        content = content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(content))
    rows = _Rows(reader)
    rows.fieldnames = tuple(reader.fieldnames or ())
    return rows


def _code_to_id(db: Session, code_col: Any, id_col: Any) -> dict[str, int]:
    """把某個 model 的 code→id 全表撈成字典，供 build()/locate() 查外鍵用。"""
    rows = db.execute(select(code_col, id_col)).all()
    return dict(rows)  # type: ignore[arg-type]


def _mapped_columns(model: type[Any]) -> set[str]:
    """回傳某個 ORM model 實際對應到資料庫欄位的屬性名稱（不含 relationship）。"""
    return {c.key for c in sa_inspect(model).mapper.column_attrs}


def _drop_none(payload: dict[str, Any]) -> dict[str, Any]:
    """去掉沒填的欄位，讓 pydantic schema 自己的預設值生效。

    空白＝不動／不設，不是「明確給 None」——後者對非 Optional 欄位（如
    ``status``、``priority``）會直接讓 pydantic 驗證失敗，蓋掉它本來就有的預設值。
    """
    return {k: v for k, v in payload.items() if v is not None}


def _resolve_code(
    ctx_map: dict[str, int], column: Column, code: str | None, entity_label: str
) -> int:
    """把 CSV 提供的 ``*_code`` 轉成內部 id；查無資料時丟出帶欄位資訊的 CellError。

    訊息不把 ``code`` 嵌進 reason——放進 CellError.value，讓同一欄「查無資料」
    的錯誤即使各列代碼不同，也能收斂成同一組（見 pipeline._group）。
    """
    if code is None:
        raise CellError(
            column.name, column.label, "", f"{column.label}為必填，不可空白"
        )
    fk_id = ctx_map.get(code)
    if fk_id is None:
        raise CellError(
            column.name,
            column.label,
            code,
            f"{column.label}對應不到現有的{entity_label}，請先建立該{entity_label}",
        )
    return fk_id


def _parse_row_cell(spec: EntitySpec, column: Column, raw: str | None) -> object:
    """逐列解析單一欄位。

    自然鍵一定要有值——沒有它連是哪一列都定不下來，所以照樣立刻報錯。其餘必填
    欄位（如案場名稱）在這裡放行空白：對既有列，空白＝不動，是既有資料的一部分；
    是不是真的能留白，等 ``create()`` 確定這是新建列時才把關（見
    ``_require_for_create``）。
    """
    if column.required and column.name not in spec.natural_key:
        return p.parse_cell(replace(column, required=False), raw)
    return p.parse_cell(column, raw)


def _require_for_create(
    spec: EntitySpec,
    payload: dict[str, Any],
    *,
    fk_specs: tuple[tuple[str, str, str, str], ...] = (),
) -> None:
    """新建列不能有必填欄位空白——這是 ``_parse_row_cell`` 延後的那一半檢查。

    已存在列的空白在 ``update()`` 早就被當作「不動」處理，不會走到這裡。

    ``fk_specs`` 是外鍵欄位（如 customer_code → customer_id）的宣告：這些欄位
    的 payload key 不是 CSV 欄名本身，而是 ``build()`` 解析後的 id 欄位，所以
    不能直接用 ``payload.get(c.name)`` 檢查。CSV 有給值但查無資料的情況已經在
    ``_resolve_code`` 擋下；這裡要抓的是 partial-update 檔案完全沒有這欄
    ——build() 因此完全沒有設定對應的 payload key，新建列仍然缺這個外鍵。
    """
    fk_targets = {csv_col: payload_field for csv_col, _, payload_field, _ in fk_specs}
    for c in spec.columns:
        if not c.required:
            continue
        target = fk_targets.get(c.name, c.name)
        if payload.get(target) is None:
            raise CellError(c.name, c.label, "", f"{c.label}為必填，不可空白")


# ctx key（preload() 放進 dict 的名字）→ 要撈 code/id 的 model。目前只有這兩種
# 外鍵目標；新增第三種時在這裡加一行即可，不用動任何 handler。
_FK_MODELS: dict[str, type[Any]] = {"farms": WindFarm, "customers": Customer}


class _BaseHandler:
    """七個 handler 共用的骨架。

    真正逐欄不同的，只有：目標 ORM model／pydantic Create model、外鍵欄位
    （``_fk_specs``：CSV 欄名 → ctx key → payload 欄位 → 中文實體名）、用什麼
    欄位查找既有列（預設 ``code``），以及 ``create()`` 要呼叫哪個 service。
    這些用類別屬性宣告，``preload`` / ``build`` / ``locate`` / ``update`` 都是
    照這些屬性泛化跑過 ``spec.columns``，不必每個 handler 各寫一份。
    """

    spec: EntitySpec
    model: type[Any]
    create_model: type[BaseModel]
    _locate_by: str = "code"
    _fk_specs: tuple[tuple[str, str, str, str], ...] = ()

    @property
    def _fk_columns(self) -> tuple[str, ...]:
        return tuple(fk[0] for fk in self._fk_specs)

    def preload(self, db: Session) -> dict[str, Any]:
        ctx_keys = {fk[1] for fk in self._fk_specs}
        return {
            key: _code_to_id(db, _FK_MODELS[key].code, _FK_MODELS[key].id)
            for key in ctx_keys
        }

    def build(self, row: dict[str, str], ctx: dict[str, Any]) -> dict[str, Any]:
        fk_columns = self._fk_columns
        payload = {
            c.name: _parse_row_cell(self.spec, c, row.get(c.name))
            for c in self.spec.columns
            if c.name in row and c.name not in fk_columns
        }
        for csv_col, ctx_key, payload_field, label in self._fk_specs:
            if csv_col not in row:
                # 這欄整個不在這份 CSV 的標題列裡——一份只更新其他欄位的
                # partial-update 檔案（§4.7）。不要求重新提供這個外鍵：
                # 不設定 payload_field，update() 就會把它當成「沒有提供」而
                # 略過不動，跟其他欄位的部分更新語意一致。新建列若因此真的
                # 缺這個外鍵，交給 create() 呼叫的 _require_for_create 用
                # 這一欄自己的中文標籤報一則清楚的錯誤。
                continue
            payload[payload_field] = _resolve_code(
                ctx[ctx_key],
                self.spec.column(csv_col),  # type: ignore[arg-type]
                p.s(row.get(csv_col)),
                label,
            )
        return payload

    def locate(
        self, db: Session, row: dict[str, str], ctx: dict[str, Any]
    ) -> Any | None:
        key = p.s(row.get(self._locate_by))
        if key is None:
            return None
        return BaseRepository(self.model, db).get_by(**{self._locate_by: key})

    def update(self, db: Session, existing: Any, payload: dict[str, Any]) -> list[str]:
        # 空白＝不動：Excel 導出常整欄空白，把它當「清空」會毀掉既有資料。
        mapped = _mapped_columns(type(existing))
        changed = []
        for name, value in payload.items():
            if value is None:
                continue
            if name not in mapped:
                # 不是 ORM 真的認得的欄位：setattr 會建立一個永遠存不進 DB 的
                # 幽靈屬性，之後每次重新匯入都會把這一列誤判成「有變更」卻什麼
                # 都沒真的改到，寧可在這裡就大聲失敗。
                raise ValueError(
                    f"「{name}」不是 {type(existing).__name__} 的欄位，無法更新"
                )
            if getattr(existing, name) != value:
                changed.append(name)
        if not changed:
            return []
        # 合併後的完整狀態要先通過驗證，才能真的寫進既有列——不然重新匯入可以把
        # end_date 改到 start_date 之前，或把 re_target_percent 改成 150；這一關
        # create() 本來就擋得住，但沒有它，bare setattr 完全不管。多出來的
        # id／created_at／updated_at 等欄位，pydantic 預設會忽略未宣告的欄位。
        merged = {col: getattr(existing, col) for col in mapped}
        merged.update({name: payload[name] for name in changed})
        self.create_model(**merged)
        for name in changed:
            setattr(existing, name, payload[name])
        db.flush()
        return changed

    def create(self, db: Session, payload: dict[str, Any]) -> None:
        raise NotImplementedError


class _FarmHandler(_BaseHandler):
    spec = schema.FARM
    model = WindFarm
    create_model = WindFarmCreate

    def create(self, db: Session, payload: dict[str, Any]) -> None:
        _require_for_create(self.spec, payload)
        wind_farm_svc.create(db, WindFarmCreate(**_drop_none(payload)))


class _CustomerHandler(_BaseHandler):
    spec = schema.CUSTOMER
    model = Customer
    create_model = CustomerCreate

    def create(self, db: Session, payload: dict[str, Any]) -> None:
        _require_for_create(self.spec, payload)
        customer_svc.create(db, CustomerCreate(**_drop_none(payload)))


class _MeterHandler(_BaseHandler):
    """電號／廠區 (Meter) 以 *customer_code* 參照所屬客戶。"""

    spec = schema.METER
    model = Meter
    create_model = MeterCreate
    _fk_specs = (("customer_code", "customers", "customer_id", "客戶"),)

    def create(self, db: Session, payload: dict[str, Any]) -> None:
        _require_for_create(self.spec, payload, fk_specs=self._fk_specs)
        # 用電名稱沒填就沿用電號代碼——只在「確定要新建」時才這樣兜底，不能放在
        # build()：build() 在 update 路徑也會跑，那樣會把既有列的名稱洗成代碼。
        payload = {**payload, "name": payload.get("name") or payload["code"]}
        meter_service.create(db, MeterCreate(**_drop_none(payload)))


class _BatteryHandler(_BaseHandler):
    """客戶側儲能 (Battery) 以 *customer_code* 參照所屬客戶。"""

    spec = schema.BATTERY
    model = Battery
    create_model = BatteryCreate
    _fk_specs = (("customer_code", "customers", "customer_id", "客戶"),)

    def create(self, db: Session, payload: dict[str, Any]) -> None:
        _require_for_create(self.spec, payload, fk_specs=self._fk_specs)
        payload = {**payload, "name": payload.get("name") or payload["code"]}
        create_battery(db, BatteryCreate(**_drop_none(payload)))


class _ContractHandler(_BaseHandler):
    """合約以 *wind_farm_code* / *customer_code* 參照案場與客戶。"""

    spec = schema.CONTRACT
    model = Contract
    create_model = ContractCreate
    _locate_by = "contract_number"
    _fk_specs = (
        ("wind_farm_code", "farms", "wind_farm_id", "案場"),
        ("customer_code", "customers", "customer_id", "客戶"),
    )

    def create(self, db: Session, payload: dict[str, Any]) -> None:
        _require_for_create(self.spec, payload, fk_specs=self._fk_specs)
        contract_svc.create(db, ContractCreate(**_drop_none(payload)))


class _GenerationHandler(_BaseHandler):
    """發電數據以 *wind_farm_code* 參照案場；自然鍵是 (案場, 期間)，不是單一
    ``code``，所以要覆寫 ``locate()``。"""

    spec = schema.GENERATION
    model = GenerationData
    create_model = GenerationCreate
    _fk_specs = (("wind_farm_code", "farms", "wind_farm_id", "案場"),)

    def locate(
        self, db: Session, row: dict[str, str], ctx: dict[str, Any]
    ) -> GenerationData | None:
        farm_id = ctx["farms"].get(p.s(row.get("wind_farm_code")))
        if farm_id is None:
            return None
        return (
            db.query(GenerationData)
            .filter_by(
                wind_farm_id=farm_id,
                period_start=p.parse_cell(
                    self.spec.column("period_start"), row.get("period_start")  # type: ignore[arg-type]
                ),
                period_end=p.parse_cell(
                    self.spec.column("period_end"), row.get("period_end")  # type: ignore[arg-type]
                ),
            )
            .first()
        )

    def create(self, db: Session, payload: dict[str, Any]) -> None:
        _require_for_create(self.spec, payload, fk_specs=self._fk_specs)
        measurement_svc.create_generation(db, GenerationCreate(**_drop_none(payload)))


class _ConsumptionHandler(_BaseHandler):
    """用電數據以 *customer_code* 參照客戶；自然鍵是 (客戶, 期間)，不是單一
    ``code``，所以要覆寫 ``locate()``。"""

    spec = schema.CONSUMPTION
    model = ConsumptionData
    create_model = ConsumptionCreate
    _fk_specs = (("customer_code", "customers", "customer_id", "客戶"),)

    def locate(
        self, db: Session, row: dict[str, str], ctx: dict[str, Any]
    ) -> ConsumptionData | None:
        cust_id = ctx["customers"].get(p.s(row.get("customer_code")))
        if cust_id is None:
            return None
        return (
            db.query(ConsumptionData)
            .filter_by(
                customer_id=cust_id,
                period_start=p.parse_cell(
                    self.spec.column("period_start"), row.get("period_start")  # type: ignore[arg-type]
                ),
                period_end=p.parse_cell(
                    self.spec.column("period_end"), row.get("period_end")  # type: ignore[arg-type]
                ),
            )
            .first()
        )

    def create(self, db: Session, payload: dict[str, Any]) -> None:
        _require_for_create(self.spec, payload, fk_specs=self._fk_specs)
        measurement_svc.create_consumption(db, ConsumptionCreate(**_drop_none(payload)))


def import_wind_farms(
    db: Session, rows: Iterable[dict], *, dry_run: bool = False
) -> ImportResult:
    return pipeline.run_import(db, schema.FARM, rows, _FarmHandler(), dry_run=dry_run)


def import_customers(
    db: Session, rows: Iterable[dict], *, dry_run: bool = False
) -> ImportResult:
    return pipeline.run_import(
        db, schema.CUSTOMER, rows, _CustomerHandler(), dry_run=dry_run
    )


def import_meters(
    db: Session, rows: Iterable[dict], *, dry_run: bool = False
) -> ImportResult:
    """Meters (電號/廠區) reference their customer by *code* in the CSV."""
    return pipeline.run_import(db, schema.METER, rows, _MeterHandler(), dry_run=dry_run)


def import_batteries(
    db: Session, rows: Iterable[dict], *, dry_run: bool = False
) -> ImportResult:
    """Batteries (客戶側儲能) reference their customer by *code* in the CSV."""
    return pipeline.run_import(
        db, schema.BATTERY, rows, _BatteryHandler(), dry_run=dry_run
    )


def import_contracts(
    db: Session, rows: Iterable[dict], *, dry_run: bool = False
) -> ImportResult:
    """Contracts reference wind farms and customers by *code* in the CSV."""
    return pipeline.run_import(
        db, schema.CONTRACT, rows, _ContractHandler(), dry_run=dry_run
    )


def import_generation(
    db: Session, rows: Iterable[dict], *, dry_run: bool = False
) -> ImportResult:
    return pipeline.run_import(
        db, schema.GENERATION, rows, _GenerationHandler(), dry_run=dry_run
    )


def import_consumption(
    db: Session, rows: Iterable[dict], *, dry_run: bool = False
) -> ImportResult:
    return pipeline.run_import(
        db, schema.CONSUMPTION, rows, _ConsumptionHandler(), dry_run=dry_run
    )
