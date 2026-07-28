"""Shared CBC solver factory with a configurable wall-clock time limit.

Keeps the matching modules free of app config: the API configures the default
time limit once at startup via ``configure_solver``; the pure solver code just
calls ``cbc()``. A time limit bounds worst-case solve duration so a pathological
input can't hang a worker — CBC returns its best incumbent instead.
"""

from __future__ import annotations

import pulp

_time_limit: float | None = None


def configure_solver(time_limit_seconds: float | None) -> None:
    global _time_limit
    _time_limit = (
        time_limit_seconds if time_limit_seconds and time_limit_seconds > 0 else None
    )


def cbc(*, exact: bool = False) -> pulp.PULP_CBC_CMD:
    """A single-threaded CBC command. ``exact`` closes the optimality gap
    (for the scenario's lexicographic solve); the configured time limit, if any,
    is always applied."""
    kwargs: dict[str, object] = {"msg": 0, "threads": 1}
    if exact:
        kwargs["gapRel"] = 0.0
        kwargs["gapAbs"] = 0.0
    if _time_limit is not None:
        kwargs["timeLimit"] = _time_limit
    return pulp.PULP_CBC_CMD(**kwargs)
