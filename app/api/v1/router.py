"""Aggregate all v1 routers."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import (
    analytics,
    consumption,
    contracts,
    customers,
    generation,
    live,
    matching,
    wind_farms,
)

api_router = APIRouter()
api_router.include_router(wind_farms.router)
api_router.include_router(customers.router)
api_router.include_router(contracts.router)
api_router.include_router(generation.router)
api_router.include_router(consumption.router)
api_router.include_router(matching.router)
api_router.include_router(analytics.router)
api_router.include_router(live.router)
