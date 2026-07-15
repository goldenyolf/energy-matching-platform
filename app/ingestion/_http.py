"""Shared HTTP GET helper for the Taipower open-data fetchers.

httpx is a core dependency, so this always works; it is a thin, injectable seam
that tests replace with a fake, and that both the monthly CSV adapter and the
real-time client reuse.
"""

from __future__ import annotations


def http_get(url: str, timeout: float = 30.0) -> bytes:
    """Fetch ``url`` and return the raw response bytes."""
    import httpx

    resp = httpx.get(url, timeout=timeout, follow_redirects=True)
    resp.raise_for_status()
    return resp.content
