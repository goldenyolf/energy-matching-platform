"""Reshape the flat hour-of-month arrays the hourly engine produces (B6).

For interval matching the engine runs over ``ndays × 24`` independent hour
buckets ordered ``index = day*24 + hour``. These helpers fold that back into a
representative 24-hour profile (sum over days per hour-of-day) and a per-day
hour×day heatmap of CFE%. Pure functions.
"""

from __future__ import annotations

from datetime import date, timedelta

_EPS = 1e-9


def days_in_period(start: date, end: date) -> int:
    """Number of calendar days from ``start`` to ``end`` inclusive."""
    return (end - start).days + 1


def hour_of_day_sums(series: list[float], ndays: int) -> list[float]:
    """Sum a length ``ndays*24`` series into 24 hour-of-day totals."""
    out = [0.0] * 24
    for i, v in enumerate(series):
        out[i % 24] += v
    return out


def heatmap_cfe(
    matched: list[float], consumption: list[float], ndays: int
) -> list[list[float]]:
    """A ``ndays × 24`` grid of CFE% (matched ÷ consumption) per (day, hour)."""
    rows: list[list[float]] = []
    for d in range(ndays):
        row: list[float] = []
        for h in range(24):
            idx = d * 24 + h
            c = consumption[idx]
            row.append(matched[idx] / c * 100.0 if c > _EPS else 0.0)
        rows.append(row)
    return rows


def day_labels(start: date, ndays: int) -> list[str]:
    """ISO date strings for each heatmap row."""
    return [(start + timedelta(days=d)).isoformat() for d in range(ndays)]
