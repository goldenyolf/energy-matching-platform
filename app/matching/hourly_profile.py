"""A9 — 逐時負載/發電曲線建模器（typical-day profiles）.

Shape a period total (monthly MWh) into a representative 24-hour profile using
typical daily shapes, so hourly (24/7 CFE) time-matching can run *before* real
15-minute AMI data exists. Each shape sums to 1.0, so ``to_hourly(total, shape)``
sums back to ``total`` — the period total is preserved (可對帳). When real
interval data arrives (Roadmap A4) it replaces these modeled profiles in place.

All values are illustrative modeled shapes, not measured data.
"""

from __future__ import annotations

HOURS = 24

# Wind: Taiwan is night-strong, weak midday (NE monsoon pattern within a day).
_WIND = [
    1.15,
    1.20,
    1.20,
    1.15,
    1.05,
    0.95,
    0.85,
    0.75,
    0.68,
    0.62,
    0.60,
    0.60,
    0.62,
    0.66,
    0.72,
    0.80,
    0.85,
    0.82,
    0.80,
    0.85,
    0.95,
    1.05,
    1.12,
    1.16,
]

# Solar: zero at night, rising after sunrise, bell peak at noon, back to zero by
# sunset — the shape that fills wind's midday trough (風光互補).
_SOLAR = [
    0.0,
    0.0,
    0.0,
    0.0,
    0.0,
    0.0,
    0.05,
    0.20,
    0.42,
    0.63,
    0.82,
    0.95,
    1.00,
    0.96,
    0.85,
    0.68,
    0.46,
    0.24,
    0.08,
    0.0,
    0.0,
    0.0,
    0.0,
    0.0,
]

# Load daily shapes by kind.
_LOAD = {
    # 半導體晶圓廠：24h 連續高基載，白天略高
    "baseload": [
        0.92,
        0.90,
        0.89,
        0.89,
        0.90,
        0.93,
        0.96,
        1.00,
        1.03,
        1.06,
        1.06,
        1.05,
        1.04,
        1.04,
        1.05,
        1.05,
        1.04,
        1.03,
        1.02,
        1.00,
        0.98,
        0.96,
        0.94,
        0.92,
    ],
    # 面板/電子/電源管理：日間雙班尖峰、傍晚肩部
    "dayshift": [
        0.60,
        0.55,
        0.52,
        0.52,
        0.55,
        0.62,
        0.75,
        0.92,
        1.05,
        1.15,
        1.20,
        1.22,
        1.18,
        1.20,
        1.22,
        1.20,
        1.15,
        1.10,
        1.05,
        0.95,
        0.85,
        0.75,
        0.68,
        0.62,
    ],
    # 生技/辦公型：白天強、夜間低
    "office": [
        0.40,
        0.35,
        0.32,
        0.32,
        0.35,
        0.42,
        0.60,
        0.85,
        1.10,
        1.25,
        1.30,
        1.28,
        1.15,
        1.25,
        1.28,
        1.20,
        1.05,
        0.85,
        0.65,
        0.55,
        0.50,
        0.48,
        0.45,
        0.42,
    ],
}

# 產業別 → 負載日型
_INDUSTRY_KIND = {
    "半導體": "baseload",
    "面板": "dayshift",
    "電子": "dayshift",
    "電源管理": "dayshift",
    "生技": "office",
}
_DEFAULT_KIND = "dayshift"


def _normalize(weights: list[float]) -> list[float]:
    total = sum(weights)
    if total <= 0:
        return [1.0 / len(weights)] * len(weights)
    return [w / total for w in weights]


def wind_shape() -> list[float]:
    """24 normalized weights (sum 1.0) for wind generation over a day."""
    return _normalize(_WIND)


def solar_shape() -> list[float]:
    """24 normalized weights (sum 1.0) for solar generation over a day."""
    return _normalize(_SOLAR)


def technology(farm_type: str | None) -> str:
    """Derive the generating technology from a site's ``farm_type``.

    Solar sites live in the same table as wind ones (``farm_type="solar"``), so
    technology is derived rather than stored — no new column, no migration.
    """
    return "solar" if (farm_type or "").lower() == "solar" else "wind"


def generation_shape(tech: str) -> list[float]:
    """The typical-day generation shape for a technology."""
    return solar_shape() if tech == "solar" else wind_shape()


def load_shape(industry: str | None) -> list[float]:
    """24 normalized weights (sum 1.0) for a customer's load, by industry."""
    kind = _INDUSTRY_KIND.get(industry or "", _DEFAULT_KIND)
    return _normalize(_LOAD[kind])


def to_hourly(total_mwh: float, shape: list[float]) -> list[float]:
    """Distribute a period total across 24 hours by ``shape``. Σ == total."""
    return [total_mwh * w for w in shape]
