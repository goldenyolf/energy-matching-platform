"""Health check endpoint."""

from __future__ import annotations

from fastapi import APIRouter

from app import __version__

router = APIRouter(tags=["system"])


@router.get("/health", summary="Liveness/health check")
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}
