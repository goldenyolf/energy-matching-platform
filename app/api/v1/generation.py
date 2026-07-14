"""Generation data endpoints (single create, CSV import, list)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Query, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.ingestion import csv_importer
from app.schemas.common import ImportResult
from app.schemas.generation import GenerationCreate, GenerationRead
from app.services import measurements as svc

router = APIRouter(prefix="/generation", tags=["generation"])


@router.get("", response_model=list[GenerationRead])
def list_generation(
    wind_farm_id: int | None = Query(default=None),
    limit: int = Query(500, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    return svc.list_generation(
        db, wind_farm_id=wind_farm_id, limit=limit, offset=offset
    )


@router.post("", response_model=GenerationRead, status_code=status.HTTP_201_CREATED)
def create_generation(payload: GenerationCreate, db: Session = Depends(get_db)):
    return svc.create_generation(db, payload)


@router.post("/import", response_model=ImportResult)
async def import_generation(
    file: UploadFile = File(..., description="CSV file of generation rows"),
    db: Session = Depends(get_db),
) -> ImportResult:
    rows = csv_importer.parse_csv(await file.read())
    return csv_importer.import_generation(db, rows)
