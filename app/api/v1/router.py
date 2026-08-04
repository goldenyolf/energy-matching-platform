"""Aggregate all v1 routers."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import (
    analytics,
    batteries,
    consumption,
    contracts,
    customers,
    generation,
    imports,
    live,
    matching,
    meters,
    trecs,
    wind_farms,
)

api_router = APIRouter()
api_router.include_router(wind_farms.router)
api_router.include_router(customers.router)
api_router.include_router(meters.router)
api_router.include_router(batteries.router)
api_router.include_router(contracts.router)
api_router.include_router(generation.router)
api_router.include_router(consumption.router)
api_router.include_router(matching.router)
api_router.include_router(analytics.router)
api_router.include_router(live.router)
api_router.include_router(trecs.router)
api_router.include_router(imports.router)
