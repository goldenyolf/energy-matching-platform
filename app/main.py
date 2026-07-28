"""FastAPI application entrypoint."""

from __future__ import annotations

import hashlib
import time
from collections.abc import Awaitable, Callable
from pathlib import Path

from fastapi import FastAPI, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.responses import Response
from starlette.types import Scope

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
from app.core.logging import configure_logging, get_logger
from app.core.ratelimit import RateLimiter
from app.matching.solver import configure_solver

configure_logging()
logger = get_logger("app")
configure_solver(settings.solver_time_limit_seconds)
_rate_limiter = RateLimiter(settings.rate_limit_per_minute)

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

# Loudly warn if a public deploy left writes wide open (see app/api/deps.py).
if settings.environment == "production" and not settings.admin_write_token:
    logger.warning(
        "ADMIN_WRITE_TOKEN is unset in production — all create/update/delete/"
        "import endpoints are OPEN to the public. Set ADMIN_WRITE_TOKEN to "
        "require an X-Admin-Token header for writes."
    )


@app.middleware("http")
async def rate_limit(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Per-IP fixed-window rate limit on the API (static SPA is exempt)."""
    if request.url.path.startswith(settings.api_v1_prefix):
        client = request.client.host if request.client else "anon"
        if not _rate_limiter.check(client, time.monotonic()):
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={"detail": "請求過於頻繁,請稍後再試。"},
            )
    return await call_next(request)


@app.middleware("http")
async def log_requests(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Log each request's method, path, status and duration; log exceptions."""
    start = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        dur = (time.perf_counter() - start) * 1000
        logger.exception(
            "%s %s failed after %.0fms", request.method, request.url.path, dur
        )
        raise
    dur = (time.perf_counter() - start) * 1000
    logger.info(
        "%s %s -> %d (%.0fms)",
        request.method,
        request.url.path,
        response.status_code,
        dur,
    )
    return response


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
_SPA_ASSETS = ("styles.css", "api.js", "app.js")


def _asset_version(web_dir: Path, name: str) -> str:
    """8-char content hash of a web asset (used to cache-bust its URL)."""
    try:
        return hashlib.sha1((web_dir / name).read_bytes()).hexdigest()[:8]
    except OSError:
        return "0"


def _render_index(web_dir: Path) -> str:
    """index.html with every JS/CSS reference cache-busted by content hash."""
    html = (web_dir / "index.html").read_text(encoding="utf-8")
    for name in _SPA_ASSETS:
        html = html.replace(f'"{name}"', f'"{name}?v={_asset_version(web_dir, name)}"')
    return html


class SpaStaticFiles(StaticFiles):
    """Serve index.html uncached (always revalidated) with content-hashed asset
    URLs, and serve the hashed JS/CSS immutably. A new deploy changes each
    asset's hash, so its URL changes and browsers fetch the new file instead of
    a stale cached copy — no manual hard-refresh needed.
    """

    async def get_response(self, path: str, scope: Scope) -> Response:
        if path.strip("/").lower() in ("", ".", "index.html"):
            html = _render_index(Path(str(self.directory)))
            return HTMLResponse(html, headers={"Cache-Control": "no-cache"})
        response = await super().get_response(path, scope)
        if path.lower().endswith((".js", ".css")):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


if _WEB_DIR.is_dir():
    app.mount("/app", SpaStaticFiles(directory=str(_WEB_DIR), html=True), name="spa")
