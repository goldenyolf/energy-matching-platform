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


def parse_csv(content: str | bytes) -> list[dict[str, str]]:
    """Parse CSV text (or bytes) into a list of row dicts."""
    if isinstance(content, bytes):
        content = content.decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(content)))


def _code_to_id(db: Session, code_col: Any, id_col: Any) -> dict[str, int]:
    """把某個 model 的 code→id 全表撈成字典，供 build()/locate() 查外鍵用。"""
    rows = db.execute(select(code_col, id_col)).all()
    return dict(rows)  # type: ignore[arg-type]


def _drop_none(payload: dict[str, Any]) -> dict[str, Any]:
    """去掉沒填的欄位，讓 pydantic schema 自己的預設值生效。

    空白＝不動／不設，不是「明確給 None」——後者對非 Optional 欄位（如
    ``status``、``priority``）會直接讓 pydantic 驗證失敗，蓋掉它本來就有的預設值。
    """
    return {k: v for k, v in payload.items() if v is not None}


def _resolve_code(
    ctx_map: dict[str, int], column: Column, code: str | None, entity_label: str
) -> int:
    """把 CSV 提供的 ``*_code`` 轉成內部 id；查無資料時丟出帶欄位資訊的 CellError。"""
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
            f"{column.label}「{code}」不存在，請先建立該{entity_label}",
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
    spec: EntitySpec, payload: dict[str, Any], *, exclude: tuple[str, ...] = ()
) -> None:
    """新建列不能有必填欄位空白——這是 ``_parse_row_cell`` 延後的那一半檢查。

    已存在列的空白在 ``update()`` 早就被當作「不動」處理，不會走到這裡。
    ``exclude`` 用來跳過改用外鍵 id 表示的欄位（如 customer_code → customer_id），
    它們的必填性已經在 ``_resolve_code`` 檢查過。
    """
    for c in spec.columns:
        if c.required and c.name not in exclude and payload.get(c.name) is None:
            raise CellError(c.name, c.label, "", f"{c.label}為必填，不可空白")


class _BaseHandler:
    """七個 handler 共用的差異比對：空白＝不動，只更新真的變了的欄位。"""

    spec: EntitySpec
    _fk_columns: tuple[str, ...] = ()

    def update(self, db: Session, existing: Any, payload: dict[str, Any]) -> list[str]:
        # 空白＝不動：Excel 導出常整欄空白，把它當「清空」會毀掉既有資料。
        changed = [
            name
            for name, value in payload.items()
            if value is not None and getattr(existing, name, None) != value
        ]
        for name in changed:
            setattr(existing, name, payload[name])
        if changed:
            db.flush()
        return changed


class _FarmHandler(_BaseHandler):
    spec = schema.FARM

    def preload(self, db: Session) -> dict[str, Any]:
        return {}  # 案場沒有外鍵，不需要預載

    def build(self, row: dict[str, str], ctx: dict[str, Any]) -> dict[str, Any]:
        return {
            c.name: _parse_row_cell(self.spec, c, row.get(c.name))
            for c in self.spec.columns
            if c.name in row
        }

    def locate(
        self, db: Session, row: dict[str, str], ctx: dict[str, Any]
    ) -> WindFarm | None:
        code = p.s(row.get("code"))
        return None if code is None else BaseRepository(WindFarm, db).get_by(code=code)

    def create(self, db: Session, payload: dict[str, Any]) -> None:
        _require_for_create(self.spec, payload)
        wind_farm_svc.create(db, WindFarmCreate(**_drop_none(payload)))


class _CustomerHandler(_BaseHandler):
    spec = schema.CUSTOMER

    def preload(self, db: Session) -> dict[str, Any]:
        return {}  # 客戶沒有外鍵，不需要預載

    def build(self, row: dict[str, str], ctx: dict[str, Any]) -> dict[str, Any]:
        return {
            c.name: _parse_row_cell(self.spec, c, row.get(c.name))
            for c in self.spec.columns
            if c.name in row
        }

    def locate(
        self, db: Session, row: dict[str, str], ctx: dict[str, Any]
    ) -> Customer | None:
        code = p.s(row.get("code"))
        return None if code is None else BaseRepository(Customer, db).get_by(code=code)

    def create(self, db: Session, payload: dict[str, Any]) -> None:
        _require_for_create(self.spec, payload)
        customer_svc.create(db, CustomerCreate(**_drop_none(payload)))


class _MeterHandler(_BaseHandler):
    """電號／廠區 (Meter) 以 *customer_code* 參照所屬客戶。"""

    spec = schema.METER
    _fk_columns = ("customer_code",)

    def preload(self, db: Session) -> dict[str, Any]:
        return {"customers": _code_to_id(db, Customer.code, Customer.id)}

    def build(self, row: dict[str, str], ctx: dict[str, Any]) -> dict[str, Any]:
        payload = {
            c.name: _parse_row_cell(self.spec, c, row.get(c.name))
            for c in self.spec.columns
            if c.name in row and c.name not in self._fk_columns
        }
        payload["customer_id"] = _resolve_code(
            ctx["customers"],
            self.spec.column("customer_code"),  # type: ignore[arg-type]
            p.s(row.get("customer_code")),
            "客戶",
        )
        # 用電名稱沒填就沿用電號代碼，維持既有匯入行為。
        payload["name"] = payload.get("name") or payload["code"]
        return payload

    def locate(
        self, db: Session, row: dict[str, str], ctx: dict[str, Any]
    ) -> Meter | None:
        code = p.s(row.get("code"))
        return None if code is None else BaseRepository(Meter, db).get_by(code=code)

    def create(self, db: Session, payload: dict[str, Any]) -> None:
        _require_for_create(self.spec, payload, exclude=self._fk_columns)
        meter_service.create(db, MeterCreate(**_drop_none(payload)))


class _BatteryHandler(_BaseHandler):
    """客戶側儲能 (Battery) 以 *customer_code* 參照所屬客戶。"""

    spec = schema.BATTERY
    _fk_columns = ("customer_code",)

    def preload(self, db: Session) -> dict[str, Any]:
        return {"customers": _code_to_id(db, Customer.code, Customer.id)}

    def build(self, row: dict[str, str], ctx: dict[str, Any]) -> dict[str, Any]:
        payload = {
            c.name: _parse_row_cell(self.spec, c, row.get(c.name))
            for c in self.spec.columns
            if c.name in row and c.name not in self._fk_columns
        }
        payload["customer_id"] = _resolve_code(
            ctx["customers"],
            self.spec.column("customer_code"),  # type: ignore[arg-type]
            p.s(row.get("customer_code")),
            "客戶",
        )
        payload["name"] = payload.get("name") or payload["code"]
        return payload

    def locate(
        self, db: Session, row: dict[str, str], ctx: dict[str, Any]
    ) -> Battery | None:
        code = p.s(row.get("code"))
        return None if code is None else BaseRepository(Battery, db).get_by(code=code)

    def create(self, db: Session, payload: dict[str, Any]) -> None:
        _require_for_create(self.spec, payload, exclude=self._fk_columns)
        create_battery(db, BatteryCreate(**_drop_none(payload)))


class _ContractHandler(_BaseHandler):
    """合約以 *wind_farm_code* / *customer_code* 參照案場與客戶。"""

    spec = schema.CONTRACT
    _fk_columns = ("wind_farm_code", "customer_code")

    def preload(self, db: Session) -> dict[str, Any]:
        return {
            "farms": _code_to_id(db, WindFarm.code, WindFarm.id),
            "customers": _code_to_id(db, Customer.code, Customer.id),
        }

    def build(self, row: dict[str, str], ctx: dict[str, Any]) -> dict[str, Any]:
        payload = {
            c.name: _parse_row_cell(self.spec, c, row.get(c.name))
            for c in self.spec.columns
            if c.name in row and c.name not in self._fk_columns
        }
        payload["wind_farm_id"] = _resolve_code(
            ctx["farms"],
            self.spec.column("wind_farm_code"),  # type: ignore[arg-type]
            p.s(row.get("wind_farm_code")),
            "案場",
        )
        payload["customer_id"] = _resolve_code(
            ctx["customers"],
            self.spec.column("customer_code"),  # type: ignore[arg-type]
            p.s(row.get("customer_code")),
            "客戶",
        )
        return payload

    def locate(
        self, db: Session, row: dict[str, str], ctx: dict[str, Any]
    ) -> Contract | None:
        number = p.s(row.get("contract_number"))
        return (
            None
            if number is None
            else BaseRepository(Contract, db).get_by(contract_number=number)
        )

    def create(self, db: Session, payload: dict[str, Any]) -> None:
        _require_for_create(self.spec, payload, exclude=self._fk_columns)
        contract_svc.create(db, ContractCreate(**_drop_none(payload)))


class _GenerationHandler(_BaseHandler):
    """發電數據以 *wind_farm_code* 參照案場；自然鍵是 (案場, 期間)。"""

    spec = schema.GENERATION
    _fk_columns = ("wind_farm_code",)

    def preload(self, db: Session) -> dict[str, Any]:
        return {"farms": _code_to_id(db, WindFarm.code, WindFarm.id)}

    def build(self, row: dict[str, str], ctx: dict[str, Any]) -> dict[str, Any]:
        payload = {
            c.name: _parse_row_cell(self.spec, c, row.get(c.name))
            for c in self.spec.columns
            if c.name in row and c.name not in self._fk_columns
        }
        payload["wind_farm_id"] = _resolve_code(
            ctx["farms"],
            self.spec.column("wind_farm_code"),  # type: ignore[arg-type]
            p.s(row.get("wind_farm_code")),
            "案場",
        )
        return payload

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
        _require_for_create(self.spec, payload, exclude=self._fk_columns)
        measurement_svc.create_generation(db, GenerationCreate(**_drop_none(payload)))


class _ConsumptionHandler(_BaseHandler):
    """用電數據以 *customer_code* 參照客戶；自然鍵是 (客戶, 期間)。"""

    spec = schema.CONSUMPTION
    _fk_columns = ("customer_code",)

    def preload(self, db: Session) -> dict[str, Any]:
        return {"customers": _code_to_id(db, Customer.code, Customer.id)}

    def build(self, row: dict[str, str], ctx: dict[str, Any]) -> dict[str, Any]:
        payload = {
            c.name: _parse_row_cell(self.spec, c, row.get(c.name))
            for c in self.spec.columns
            if c.name in row and c.name not in self._fk_columns
        }
        payload["customer_id"] = _resolve_code(
            ctx["customers"],
            self.spec.column("customer_code"),  # type: ignore[arg-type]
            p.s(row.get("customer_code")),
            "客戶",
        )
        return payload

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
        _require_for_create(self.spec, payload, exclude=self._fk_columns)
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
