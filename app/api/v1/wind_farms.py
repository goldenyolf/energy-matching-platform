"""Wind farm endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.schemas.wind_farm import WindFarmCreate, WindFarmRead
from app.services import wind_farms as svc

router = APIRouter(prefix="/wind-farms", tags=["wind-farms"])


@router.get("", response_model=list[WindFarmRead])
def list_wind_farms(
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    return svc.list_all(db, limit=limit, offset=offset)


@router.post("", response_model=WindFarmRead, status_code=status.HTTP_201_CREATED)
def create_wind_farm(payload: WindFarmCreate, db: Session = Depends(get_db)):
    return svc.create(db, payload)


@router.get("/{farm_id}", response_model=WindFarmRead)
def get_wind_farm(farm_id: int, db: Session = Depends(get_db)):
    return svc.get(db, farm_id)
