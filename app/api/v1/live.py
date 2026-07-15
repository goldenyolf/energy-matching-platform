"""Real-time renewables monitoring endpoint (read-through, not persisted)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status

from app.ingestion.taipower_live import LiveClient
from app.schemas.live import LiveRenewables

router = APIRouter(prefix="/live", tags=["live"])

# Module-level client so its TTL cache is shared across requests. Tests replace
# this with a client wired to an injected fetch.
_client = LiveClient()


@router.get("/renewables", response_model=LiveRenewables)
def live_renewables(force: bool = Query(False, description="bypass the TTL cache")):
    """Current Taipower wind units and renewable-type totals (instantaneous MW)."""
    try:
        return _client.get(force=force)
    except Exception as exc:  # noqa: BLE001 - upstream/parse errors → 503
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"台電即時資料暫時無法取得:{exc}",
        ) from exc
