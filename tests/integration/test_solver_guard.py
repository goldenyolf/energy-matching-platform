"""The solver-slot dependency returns 503 when all slots are taken."""

from __future__ import annotations

from app.api import deps
from app.core.config import settings


def test_optimize_returns_503_when_solver_saturated(client, monkeypatch):
    monkeypatch.setattr(settings, "solver_acquire_timeout_seconds", 0.05)
    # Drain every solver permit so the endpoint's dependency can't acquire one.
    held = 0
    while deps._solver_sem.acquire(blocking=False):
        held += 1
    try:
        resp = client.get("/api/v1/matching/optimize?period=2024-01")
        assert resp.status_code == 503
        assert "忙碌" in resp.json()["detail"]
    finally:
        for _ in range(held):
            deps._solver_sem.release()


def test_optimize_ok_when_slot_available(client):
    # With all permits free, the same endpoint solves normally.
    resp = client.get("/api/v1/matching/optimize?period=2024-01")
    assert resp.status_code == 200
