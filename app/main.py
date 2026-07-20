"""FastAPI application entrypoint."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.api.v1.health import router as health_router
from app.api.v1.router import api_router
from app.core.config import settings
from app.core.exceptions import (
    ConflictError,
    DomainError,
    NotFoundError,
    ValidationError,
)

_HTTP_422 = 422  # Unprocessable content (avoids a renamed-constant deprecation)

app = FastAPI(
    title=settings.app_name,
    version=__version__,
    description=(
        "MVP for wind power data management, renewable energy contracts, "
        "green energy allocation, and RE target analytics in Taiwan. "
        "Demo data is simulated; not affiliated with any energy company."
    ),
)

# Health at root (per spec) and under the versioned prefix.
app.include_router(health_router)
app.include_router(api_router, prefix=settings.api_v1_prefix)


_STATUS_MAP: dict[type[DomainError], int] = {
    NotFoundError: status.HTTP_404_NOT_FOUND,
    ConflictError: status.HTTP_409_CONFLICT,
    ValidationError: _HTTP_422,
}


@app.exception_handler(DomainError)
async def domain_error_handler(_: Request, exc: DomainError) -> JSONResponse:
    code = _STATUS_MAP.get(type(exc), status.HTTP_400_BAD_REQUEST)
    return JSONResponse(status_code=code, content={"detail": str(exc)})


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    # The web UI lives at /app; send visitors there instead of the API index.
    return RedirectResponse(url="/app/")


@app.get("/api", tags=["system"], summary="API index")
def api_index() -> dict[str, str]:
    return {
        "name": settings.app_name,
        "version": __version__,
        "docs": "/docs",
        "health": "/health",
        "app": "/app/",
    }


# Static SPA (v1) served same-origin at /app so it can call /api/v1 without CORS.
_WEB_DIR = Path(__file__).resolve().parents[1] / "web"
if _WEB_DIR.is_dir():
    app.mount("/app", StaticFiles(directory=str(_WEB_DIR), html=True), name="spa")
