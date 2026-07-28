"""Contract (PPA) endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Query, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, read_upload, require_write_access
from app.ingestion import csv_importer
from app.schemas.common import ImportResult
from app.schemas.contract import ContractCreate, ContractRead, ContractUpdate
from app.services import contracts as svc

router = APIRouter(prefix="/contracts", tags=["contracts"])
_write = Depends(require_write_access)


@router.post("/import", response_model=ImportResult, dependencies=[_write])
async def import_contracts(
    file: UploadFile = File(..., description="CSV of contract rows"),
    db: Session = Depends(get_db),
) -> ImportResult:
    rows = csv_importer.parse_csv(await read_upload(file))
    return csv_importer.import_contracts(db, rows)


@router.get("", response_model=list[ContractRead])
def list_contracts(
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    return svc.list_all(db, limit=limit, offset=offset)


@router.post(
    "",
    response_model=ContractRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_write],
)
def create_contract(payload: ContractCreate, db: Session = Depends(get_db)):
    return svc.create(db, payload)


@router.get("/{contract_id}", response_model=ContractRead)
def get_contract(contract_id: int, db: Session = Depends(get_db)):
    return svc.get(db, contract_id)


@router.put("/{contract_id}", response_model=ContractRead, dependencies=[_write])
def update_contract(
    contract_id: int, payload: ContractUpdate, db: Session = Depends(get_db)
):
    return svc.update(db, contract_id, payload)


@router.delete(
    "/{contract_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[_write]
)
def delete_contract(contract_id: int, db: Session = Depends(get_db)) -> None:
    svc.delete(db, contract_id)
