"""CSV import: parse CSV content into domain rows and persist them.

Each importer is idempotent on the entity's natural key (code / contract_number),
skipping rows that already exist and collecting per-row errors rather than
aborting the whole file.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable

from sqlalchemy.orm import Session

from app.core.exceptions import DomainError
from app.ingestion import parsing as p
from app.models.enums import ContractStatus, GreenTargetType, WindFarmStatus
from app.schemas.common import ImportResult
from app.schemas.consumption import ConsumptionCreate
from app.schemas.contract import ContractCreate
from app.schemas.customer import CustomerCreate
from app.schemas.generation import GenerationCreate
from app.schemas.wind_farm import WindFarmCreate
from app.services import contracts as contract_svc
from app.services import customers as customer_svc
from app.services import measurements as measurement_svc
from app.services import wind_farms as wind_farm_svc


def parse_csv(content: str | bytes) -> list[dict[str, str]]:
    """Parse CSV text (or bytes) into a list of row dicts."""
    if isinstance(content, bytes):
        content = content.decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(content)))


def _lookup_id(db: Session, model: type, code: str | None) -> int | None:
    if code is None:
        return None
    from app.repositories.base import BaseRepository  # local import

    row = BaseRepository(model, db).get_by(code=code)
    return row.id if row else None


def import_wind_farms(db: Session, rows: Iterable[dict]) -> ImportResult:
    imported, skipped, errors = 0, 0, []
    for n, row in enumerate(rows, start=2):
        try:
            data = WindFarmCreate(
                code=p.s(row.get("code")),
                name=p.s(row.get("name")),
                operator_name=p.s(row.get("operator_name")),
                location=p.s(row.get("location")),
                installed_capacity_mw=p.f(row.get("installed_capacity_mw")),
                feed_in_price_per_kwh=p.f(row.get("feed_in_price_per_kwh")),
                commercial_operation_date=p.d(row.get("commercial_operation_date")),
                status=WindFarmStatus(
                    p.s(row.get("status")) or WindFarmStatus.OPERATIONAL.value
                ),
            )
            wind_farm_svc.create(db, data)
            imported += 1
        except DomainError:
            skipped += 1
        except Exception as exc:  # noqa: BLE001 - report row-level errors
            errors.append(f"row {n}: {exc}")
    return ImportResult(imported=imported, skipped=skipped, errors=errors)


def import_customers(db: Session, rows: Iterable[dict]) -> ImportResult:
    imported, skipped, errors = 0, 0, []
    for n, row in enumerate(rows, start=2):
        try:
            data = CustomerCreate(
                code=p.s(row.get("code")),
                company_name=p.s(row.get("company_name")),
                industry=p.s(row.get("industry")),
                annual_consumption_mwh=p.f(row.get("annual_consumption_mwh")) or 0.0,
                re_target_percent=p.f(row.get("re_target_percent")) or 0.0,
                target_year=p.i(row.get("target_year")),
                green_target_type=GreenTargetType(
                    p.s(row.get("green_target_type"))
                    or GreenTargetType.RE_PERCENT.value
                ),
                target_energy_mwh=p.f(row.get("target_energy_mwh")),
            )
            customer_svc.create(db, data)
            imported += 1
        except DomainError:
            skipped += 1
        except Exception as exc:  # noqa: BLE001
            errors.append(f"row {n}: {exc}")
    return ImportResult(imported=imported, skipped=skipped, errors=errors)


def import_meters(db: Session, rows: Iterable[dict]) -> ImportResult:
    """Meters (電號/廠區) reference their customer by *code* in the CSV."""
    from app.models import Customer, Meter

    imported, skipped, errors = 0, 0, []
    for n, row in enumerate(rows, start=2):
        try:
            code = p.s(row.get("code"))
            cust_id = _lookup_id(db, Customer, p.s(row.get("customer_code")))
            if code is None or cust_id is None:
                errors.append(f"row {n}: missing code or unknown customer_code")
                continue
            if _lookup_id(db, Meter, code) is not None:
                skipped += 1
                continue
            db.add(
                Meter(
                    code=code,
                    customer_id=cust_id,
                    name=p.s(row.get("name")) or code,
                    location=p.s(row.get("location")),
                    re_target_percent=p.f(row.get("re_target_percent")) or 0.0,
                    annual_consumption_mwh=p.f(row.get("annual_consumption_mwh")),
                )
            )
            db.commit()
            imported += 1
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            errors.append(f"row {n}: {exc}")
    return ImportResult(imported=imported, skipped=skipped, errors=errors)


def import_contracts(db: Session, rows: Iterable[dict]) -> ImportResult:
    """Contracts reference wind farms and customers by *code* in the CSV."""
    from app.models import Customer, WindFarm

    imported, skipped, errors = 0, 0, []
    for n, row in enumerate(rows, start=2):
        try:
            wf_id = _lookup_id(db, WindFarm, p.s(row.get("wind_farm_code")))
            cust_id = _lookup_id(db, Customer, p.s(row.get("customer_code")))
            if wf_id is None or cust_id is None:
                errors.append(f"row {n}: unknown wind_farm_code or customer_code")
                continue
            data = ContractCreate(
                contract_number=p.s(row.get("contract_number")),
                wind_farm_id=wf_id,
                customer_id=cust_id,
                start_date=p.d(row.get("start_date")),
                end_date=p.d(row.get("end_date")),
                contracted_energy_mwh=p.f(row.get("contracted_energy_mwh")),
                contracted_percentage=p.f(row.get("contracted_percentage")),
                price_per_kwh=p.f(row.get("price_per_kwh")),
                priority=p.i(row.get("priority")) or 100,
                status=ContractStatus(
                    p.s(row.get("status")) or ContractStatus.ACTIVE.value
                ),
            )
            contract_svc.create(db, data)
            imported += 1
        except DomainError:
            skipped += 1
        except Exception as exc:  # noqa: BLE001
            errors.append(f"row {n}: {exc}")
    return ImportResult(imported=imported, skipped=skipped, errors=errors)


def import_generation(db: Session, rows: Iterable[dict]) -> ImportResult:
    from app.models import WindFarm

    imported, skipped, errors = 0, 0, []
    for n, row in enumerate(rows, start=2):
        try:
            wf_id = p.i(row.get("wind_farm_id")) or _lookup_id(
                db, WindFarm, p.s(row.get("wind_farm_code"))
            )
            if wf_id is None:
                errors.append(f"row {n}: unknown wind farm")
                continue
            data = GenerationCreate(
                wind_farm_id=wf_id,
                period_start=p.d(row.get("period_start")),
                period_end=p.d(row.get("period_end")),
                generated_energy_mwh=p.f(row.get("generated_energy_mwh")),
                data_source=p.s(row.get("data_source")) or "mock",
            )
            measurement_svc.create_generation(db, data)
            imported += 1
        except DomainError as exc:
            errors.append(f"row {n}: {exc}")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"row {n}: {exc}")
    return ImportResult(imported=imported, skipped=skipped, errors=errors)


def import_consumption(db: Session, rows: Iterable[dict]) -> ImportResult:
    from app.models import Customer

    imported, skipped, errors = 0, 0, []
    for n, row in enumerate(rows, start=2):
        try:
            cust_id = p.i(row.get("customer_id")) or _lookup_id(
                db, Customer, p.s(row.get("customer_code"))
            )
            if cust_id is None:
                errors.append(f"row {n}: unknown customer")
                continue
            data = ConsumptionCreate(
                customer_id=cust_id,
                period_start=p.d(row.get("period_start")),
                period_end=p.d(row.get("period_end")),
                consumed_energy_mwh=p.f(row.get("consumed_energy_mwh")),
                data_source=p.s(row.get("data_source")) or "mock",
            )
            measurement_svc.create_consumption(db, data)
            imported += 1
        except DomainError as exc:
            errors.append(f"row {n}: {exc}")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"row {n}: {exc}")
    return ImportResult(imported=imported, skipped=skipped, errors=errors)
